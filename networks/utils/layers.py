from typing import Any

import numpy as np
import torch
from torch import Tensor, nn


class MinibatchStdDev(nn.Module):
    """
    Calculates the minibatch standard deviation and adds it to the output.

    Calculates the average standard deviation of each value in the input
    map across the channels and concatenates a blown up version of it
    (same size as the input map) to the input
    """

    def __init__(self, group_size: int = 4, num_new_features: int = 1):
        super(MinibatchStdDev, self).__init__()
        self.group_size = group_size
        self.num_new_features = num_new_features

    def forward(self, x):
        b, c, h, w = x.shape
        group_size = min(self.group_size, b)
        y = x.reshape(
            [
                group_size,
                -1,
                self.num_new_features,
                c // self.num_new_features,
                h,
                w,
            ]
        )
        y = y - y.mean(0, keepdim=True)
        y = (y**2).mean(0, keepdim=True)
        y = (y + 1e-8) ** 0.5
        y = y.mean([3, 4, 5], keepdim=True).squeeze(
            3
        )  # don't keep the meaned-out channels
        y = (
            y.expand(group_size, -1, -1, h, w)
            .clone()
            .reshape(b, self.num_new_features, h, w)
        )
        z = torch.cat([x, y], dim=1)
        return z


class ScaledDense(nn.Linear):
    def __init__(
        self,
        in_features,
        out_features,
        bias=True,
        gain: float = None,
        use_dynamic_wscale: bool = True,
        learning_rate_multiplier: float = 1.0,
    ):
        """
        Dense layer with weight scaling.

        Ordinary Dense layer, that scales the weights by He's scaling
        factor at each forward pass. He's scaling factor is defined as
        sqrt(2/fan_in) where fan_in is the number of input units of the
        layer
        """
        super().__init__(in_features, out_features, bias)
        self.use_dynamic_wscale = use_dynamic_wscale
        self.learning_rate_multiplier = learning_rate_multiplier

        torch.nn.init.normal_(self.weight)
        if bias:
            torch.nn.init.zeros_(self.bias)

        if self.use_dynamic_wscale:
            gain = gain if gain else np.sqrt(2)
            fan_in = self.in_features
            self.gain = gain / np.sqrt(max(1.0, fan_in))

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        bias = self.bias * self.learning_rate_multiplier
        weights = self.weight * self.learning_rate_multiplier
        if self.use_dynamic_wscale:
            return nn.functional.linear(x, weights * self.gain, self.bias)
        return nn.functional.linear(x, weights, bias)


class ScaledConv2dTranspose(nn.ConvTranspose2d):
    def __init__(
        self,
        in_channels,
        out_channels,
        kernel_size,
        stride=1,
        padding=0,
        output_padding=0,
        groups=1,
        bias=True,
        dilation=1,
        padding_mode="zeros",
        use_dynamic_wscale: bool = True,
        gain: float = None,
    ) -> None:
        super().__init__(
            in_channels,
            out_channels,
            kernel_size,
            stride,
            padding,
            output_padding,
            groups,
            bias,
            dilation,
            padding_mode,
        )
        torch.nn.init.normal_(self.weight)
        if bias:
            torch.nn.init.zeros_(self.bias)

        self.use_dynamic_wscale = use_dynamic_wscale
        if self.use_dynamic_wscale:
            gain = gain if gain else np.sqrt(2)
            fan_in = np.prod(self.kernel_size) * self.in_channels
            self.gain = gain / np.sqrt(max(1.0, fan_in))

    def forward(
        self, x: torch.Tensor, output_size: Any = None
    ) -> torch.Tensor:
        output_padding = self._output_padding(
            input, output_size, self.stride, self.padding, self.kernel_size
        )
        weight = (
            self.weight * self.gain if self.use_dynamic_wscale else self.weight
        )
        return torch.conv_transpose2d(
            input=x,
            weight=weight,  # scale the weight on runtime
            bias=self.bias,
            stride=self.stride,
            padding=self.padding,
            output_padding=output_padding,
            groups=self.groups,
            dilation=self.dilation,
        )


class ScaledConv2d(nn.Conv2d):
    def __init__(
        self,
        in_channels,
        out_channels,
        kernel_size,
        stride=1,
        padding=0,
        dilation=1,
        groups=1,
        bias=True,
        padding_mode="zeros",
        use_dynamic_wscale: bool = True,
        gain: float = None,
    ):
        """
        Scaled Convolutional Layer.

        Scales the weights on each forward pass down to by He's initialization
        factor. For Progressive Growing GANS this results in an equalized
        learning rate for all layers, where bigger layers are scaled down.

        Args:
            gain: Constant to upscale the weight sclaing
            use_dynamic_wscale: Switch on or off dynamic weight scaling.
                Switching it off results in a ordinary 2D convolutional layer.
            **kwargs:
        """
        super().__init__(
            in_channels,
            out_channels,
            kernel_size,
            stride,
            padding,
            dilation,
            groups,
            bias,
            padding_mode,
        )
        torch.nn.init.normal_(self.weight)
        if bias:
            torch.nn.init.zeros_(self.bias)

        self.use_dynamic_wscale = use_dynamic_wscale
        if self.use_dynamic_wscale:
            gain = gain if gain else np.sqrt(2)
            fan_in = np.prod(self.kernel_size) * self.in_channels
            self.gain = gain / np.sqrt(max(1.0, fan_in))

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        weight = (
            self.weight * self.gain if self.use_dynamic_wscale else self.weight
        )
        return torch.conv2d(
            input=x,
            weight=weight,
            bias=self.bias,
            stride=self.stride,
            padding=self.padding,
            dilation=self.dilation,
            groups=self.groups,
        )


class PixelwiseNorm(nn.Module):
    def __init__(self):
        super(PixelwiseNorm, self).__init__()
        self.alpha = 1e-8

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        y = torch.sqrt(torch.mean(x**2, dim=1, keepdim=True) + self.alpha)
        return x / y


class Truncation(nn.Module):
    def __init__(self, avg_latent, max_layer=8, threshold=0.7, beta=0.995):
        """
        Applies the Truncation trick as described in the paper `A Style-Based
        Generator Architecture for Generative Adversarial Networks`

        Args:
            avg_latent: Average latent vector from the mapping network
            max_layer: Maximum number of layers to apply the truncation
            threshold: Truncation threshold
            beta: Weighting factor for the average latent vector calculation
        """

        super().__init__()
        self.max_layer = max_layer
        self.threshold = threshold
        self.beta = beta
        self.register_buffer("avg_latent", avg_latent)

    def update(self, last_avg: Tensor):
        """
        Updates the average latent vector with the last latent vector.

        Args:
            last_avg: Last average latent vector
        """
        self.avg_latent.copy_(
            self.beta * self.avg_latent + (1.0 - self.beta) * last_avg
        )

    def forward(self, x: Tensor) -> Tensor:
        """
        Applies the truncation trick to the input tensor.

        Args:
            x: Input tensor
        """
        interpolation = torch.lerp(self.avg_latent, x, self.threshold)
        layer_is_valid = torch.arange(x.size(1)) < self.max_layer
        layer_is_valid = layer_is_valid.view(1, -1, 1).to(x.device)
        return torch.where(layer_is_valid, interpolation, x)
