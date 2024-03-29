import random

import numpy as np
import torch
from torch import Tensor, nn

from networks.utils import calc_channels_at_stage
from networks.utils.layers import (
    PixelwiseNorm,
    ScaledConv2d,
    ScaledConv2dTranspose,
    ScaledDense,
    Truncation,
)


class StyleGANMappingNetwork(nn.Module):
    def __init__(
        self, latent_size: int, mapping_layers: int, broadcast_dim: int
    ):
        """
        StyleGan Mapping Network as described in the paper `A Style-Based
        Generator Architecture for Generative Adversarial Networks`

        Args:
            latent_size: Size of the latent space
            mapping_layers: Number of layers in the mapping network
            broadcast_dim: Total Number of blocks the Generator is composed of

        References:
            https://arxiv.org/pdf/1812.04948.pdf
        """
        super().__init__()
        self.n_blocks = broadcast_dim
        self.lrelu = nn.LeakyReLU(0.2)
        self.mapping_network = nn.ModuleList([PixelwiseNorm()])
        for _ in range(mapping_layers):
            self.mapping_network.append(
                ScaledDense(
                    latent_size,
                    latent_size,
                    gain=np.sqrt(2),
                    learning_rate_multiplier=0.01,
                )
            )
            self.mapping_network.append(self.lrelu)

    def forward(self, x: Tensor):
        """
        Passes the input tensor through the mapping network.

        Args:
            x: Latent space vector
        """
        for layer in self.mapping_network:
            x = layer(x)
        return x.unsqueeze(1).expand(-1, self.n_blocks, -1)


class Epilogue(nn.Module):
    def __init__(self, n_channels: int, latent_size: int):
        """
        Epilogue block that gets executed after every Conv2d layer.

        Args:
            n_channels: Number of channels
            latent_size: Latent space size
        """
        super().__init__()

        self.noise_mix_in = NoiseMixIn()
        self.lrealu = nn.LeakyReLU(0.2)
        self.instance_norm = nn.InstanceNorm2d(n_channels)
        self.style_mix_in = StyleMixIn(latent_size, n_channels)

    def forward(self, x: Tensor, w: Tensor, seed: int = None) -> Tensor:
        """
        Passes the input tensor through the layers and mixes in the latent
        vector w form the mapping network.

        Args:
            x: Input tensor from the last Conv2d layer
            w: Latent vector from the mapping network
        """
        x = self.noise_mix_in(x, seed=seed)
        x = self.lrealu(x)
        x = self.instance_norm(x)
        return self.style_mix_in(x, w)


class NoiseMixIn(nn.Module):
    def __init__(self):
        """
        Injects noise into the input tensor.
        """
        super().__init__()
        self.weight = nn.Parameter(torch.zeros(1))
        self.bias = nn.Parameter(torch.zeros(1))

    def forward(self, x: Tensor, seed: int = None) -> Tensor:
        """
        Randomly generates noise and mixes it with the input tensor.

        Args:
            x: Input tensor
        """
        if seed is not None:
            torch.manual_seed(seed)
        noise = torch.randn(
            x.size(0), 1, x.size(2), x.size(3), device=x.device, dtype=x.dtype
        )
        noise = noise.expand(x.size(0), 1, x.size(2), x.size(3))
        return (
            x
            + self.weight.view(1, -1, 1, 1) * noise
            + self.bias.view(1, -1, 1, 1)
        )


class StyleMixIn(nn.Module):
    def __init__(self, latent_size: int, n_channels: int):
        """
        StyleGAN adaptive instance normalization.

        Args:
            latent_size: Size of the latent space
            n_channels: Number of channels
        """
        super(StyleMixIn, self).__init__()
        self.dense = ScaledDense(latent_size, n_channels * 2, gain=1.0)

    def forward(self, x: Tensor, w: Tensor) -> Tensor:
        """
        Each feature map xi is normalized separately, and then scaled and
        biased using the corresponding scalar components from style w.

        Args:
            x: Input tensor
            w: Latent vector from the mapping network
        """
        style = self.dense(w)
        shape = [-1, 2, x.size(1)] + (x.dim() - 2) * [1]
        style = style.view(shape)
        return x * (style[:, 0] + 1.0) + style[:, 1]


class StyleGANGenInitialBlock(nn.Module):
    def __init__(self, n_channels: int, latent_size: int):
        """
        Initial block of the StyleGAN generator.

        Args:
            n_channels: Number of channels of the image
            latent_size: Dimensionality of the latent space
        """
        super().__init__()
        self.n_channels = n_channels

        self.const = nn.Parameter(torch.ones(1, n_channels, 4, 4))

        self.epilogue_1 = Epilogue(n_channels, latent_size)
        self.conv = ScaledConv2d(
            n_channels,
            n_channels,
            kernel_size=3,
            padding=1,
        )
        self.epilogue_2 = Epilogue(n_channels, latent_size)

    def forward(self, w: Tensor, seed: int = None) -> Tensor:
        """
        Passes the latent vector w through the initial block of the generator.
        Specifically, the latent vector is mixed with the noise, normalized and
        then mixed with the constant input tensor (in the epilogue). After that
        a ScaledConv2d is applied to the input tensor and the epilogue is
        applied to its output.

        Args:
            w: Latent vector from the mapping network
        """
        batch_size = w.size(0)
        x = self.const.expand(batch_size, -1, -1, -1)
        x = self.epilogue_1(x, w[:, 0], seed=seed)
        x = self.conv(x)
        return self.epilogue_2(x, w[:, 1], seed=seed)


class StyleGANGenGeneralConvBlock(nn.Module):
    def __init__(self, in_channels: int, out_channels: int, latent_size: int):
        """
        General convolution block of the StyleGAN generator.

        Args:
            in_channels: Number of input channels to the block
            out_channels: Number of output channels required
            latent_size: Dimensionality of the latent space
        """
        super().__init__()

        self.conv_1 = ScaledConv2dTranspose(
            in_channels,
            out_channels,
            kernel_size=3,
            padding=1,
            use_dynamic_wscale=True,
        )
        self.epilogue_1 = Epilogue(out_channels, latent_size)
        self.conv_2 = ScaledConv2d(
            out_channels,
            out_channels,
            kernel_size=3,
            padding=1,
            use_dynamic_wscale=True,
        )
        self.epilogue_2 = Epilogue(out_channels, latent_size)
        self.upsample = nn.UpsamplingBilinear2d(scale_factor=2.0)

    def forward(self, x: Tensor, w: Tensor, seed: int = None) -> Tensor:
        """
        Forward pass of the general convolution block. Specifically, scales the
        input tensor up by a factor of 2, applies the first ScaledConv2d and
        then applies the epilogue operations (Mixing with noise, LeakyRelu,
        Instance Normalization and Adaptive Input Normalization with the
        latent_space). After that, applies the second ScaledConv2d and again
        runs the epilogue operations.

        Args:
            x: Output of the previous block
            w: Latent vector from the mapping network
        """
        x = self.conv_1(x)
        x = self.epilogue_1(x, w[:, 0], seed=seed)
        x = self.conv_2(x)
        return self.epilogue_2(x, w[:, 1], seed=seed)


class StyleGANSynthesis(nn.Module):
    def __init__(
        self,
        n_blocks: int = 10,
        latent_size: int = 512,
        n_channels: int = 3,
    ):
        """
        StyleGAN synthesis network as defined in the referenced paper. Similar
        to a ProGAN, this networks grows progressively during training. The
        main difference is that a mapping network is not used to generate the
        latent vector w.

        Args:
            n_blocks: Number of blocks of the StyleGAN. Final
            latent_size: Dimensionality of the latent space
            n_channels: Number of channels in the output image
        """
        super().__init__()

        self.n_blocks = n_blocks
        self.initial_block = StyleGANGenInitialBlock(
            calc_channels_at_stage(0), latent_size
        )

        self.pro_blocks = nn.ModuleList()
        self.to_rgb = nn.ModuleList()

        for block in range(0, n_blocks):
            self.pro_blocks.append(
                StyleGANGenGeneralConvBlock(
                    calc_channels_at_stage(block),
                    calc_channels_at_stage(block + 1),
                    latent_size=latent_size,
                )
            )
            self.to_rgb.append(
                ScaledConv2d(
                    calc_channels_at_stage(block),
                    n_channels,
                    kernel_size=(1, 1),
                    gain=1.0,
                )
            )
        self.pro_blocks.append(
            ScaledConv2d(
                calc_channels_at_stage(n_blocks),
                n_channels,
                kernel_size=1,
                gain=1,
            )
        )
        self.upsample = nn.UpsamplingBilinear2d(scale_factor=2.0)

    def forward(
        self,
        w: Tensor,
        block: int = 0,
        alpha: float = 0.0,
        seed: int = None,
    ) -> Tensor:
        if block > self.n_blocks:
            raise ValueError(
                f"This model only has {self.n_blocks} blocks. depth parameter has to be <= n_blocks"
            )
        x = self.initial_block(w[:, 0:2], seed=seed)
        if block == 0:
            return self.to_rgb[0](x)
        for i, pro_block in enumerate(self.pro_blocks[:block], start=1):
            upscaled = self.upsample(x)
            x = pro_block(upscaled, w[:, 2 * i : 2 * i + 2], seed=seed)
        residual = self.to_rgb[block - 1](upscaled)
        straight = self.to_rgb[block](x)
        return (alpha * straight) + ((1 - alpha) * residual)


class StyleGANGenerator(nn.Module):
    def __init__(
        self,
        n_blocks: int = 10,
        latent_size: int = 512,
        n_channels: int = 3,
        n_mapping: int = 8,
        style_mixing_prob=0.9,
    ):
        super(StyleGANGenerator, self).__init__()

        self.n_blocks = n_blocks
        self.latent_size = latent_size
        self.n_channels = n_channels

        self.style_mixing_prob = style_mixing_prob
        self.truncation = Truncation(
            avg_latent=torch.zeros(latent_size),
            max_layer=8,
            threshold=0.7,
            beta=0.995,
        )

        self.g_mapping = StyleGANMappingNetwork(
            latent_size, n_mapping, broadcast_dim=(self.n_blocks + 2) * 2 - 2
        )
        self.g_synthesis = StyleGANSynthesis(
            n_blocks=n_blocks, latent_size=latent_size, n_channels=n_channels
        )
        self.upsample = self.g_synthesis.upsample

    def forward(
        self,
        x: Tensor,
        year: Tensor = None,
        block: int = 0,
        alpha: float = 1.0,
        seed: int = None,
    ):
        w_orig = self.g_mapping(x)

        if self.training:
            self.truncation.update(w_orig[0, 0].detach())
            x_rand = torch.randn(x.shape).to(x.device)
            w_rand = self.g_mapping(x_rand)
            layer_idx = torch.from_numpy(
                np.arange(self.g_mapping.n_blocks)[np.newaxis, :, np.newaxis]
            ).to(x.device)
            cur_layers = 2 * (block + 1)
            mixing_cutoff = (
                random.randint(1, cur_layers)
                if random.random() < self.style_mixing_prob
                else cur_layers
            )
            w_orig = torch.where(layer_idx < mixing_cutoff, w_orig, w_rand)

            w_orig = self.truncation(w_orig)

        return self.g_synthesis(w_orig, block, alpha, seed=seed)
