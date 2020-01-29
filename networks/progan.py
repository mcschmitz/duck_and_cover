import functools

import numpy as np
from keras import Model
from keras import backend as K
from keras.initializers import RandomNormal
from keras.layers import *

from networks import GAN
from networks.utils import PixelNorm, RandomWeightedAverage, wasserstein_loss, gradient_penalty_loss
from networks.utils.layers import MinibatchSd, WeightedSum, ScaledDense, ScaledConv2D


#  TODO Add release year information
#  TODO Add genre information
#  TODO Add artist
#  TODO add album name


class ProGAN(GAN):

    def __init__(self, gradient_penalty_weight: int = 10, latent_size: int = 256):
        """Progressive growing GAN

        Progressive Growing GAN that iteratively adds convolutional blocks too generator and discriminator. This
        results in improved quality, stability, variation and a faster learning time. Initialization itself is
        similar to the a normal Wasserstein GAN. Training, however, is slightly different: Initialization of the
        training phase should be done on a small scale image (e.g. 4x4). After an initial burn-in phase (train the
        GAN on the current resolution), a fade-in phase follows; meaning that on fades in the 8x8 upscale layer using
        the add add_fade_in_layers method. This phase is followed by another burn-in phase on the current image
        resolution. The procedure is repeated until the output image has the desired resolution.

        Args:
            gradient_penalty_weight: weight for the gradient penalty
            latent_size: Size of the latent vector that is used to generate the image
        """
        super(ProGAN, self).__init__()
        self.img_height = None
        self.img_width = None
        self.channels = None
        self.img_shape = (self.img_height, self.img_width, self.channels)
        self.latent_size = latent_size
        self.discriminator_loss = []
        self._gradient_penalty_weight = gradient_penalty_weight
        self.batch_size = None

    def build_models(self, optimizer, discriminator_optimizer=None, batch_size: int = None,
                     image_resolution: int = None, channels: int = None, compile_only: bool = False):
        """Builds the desired GAN that allows to generate covers.
        @ TODO
        Builds the generator, the discriminator and the combined model for a WGAN using Wasserstein loss with gradient
        penalty to improve learning.

        Args:
            optimizer: Which optimizer to use
            discriminator_optimizer: Which optimizer to use for the discriminator model
            compile_only: Whether to only compile the models. Needed for fade-in phase
            image_resolution: resolution of the output image
            channels: number of channels of the output image
            batch_size: batch size of the GAN
        """
        self.img_height = np.int(image_resolution) if image_resolution is not None else self.img_height
        self.img_width = np.int(image_resolution) if image_resolution is not None else self.img_width
        self.channels = channels if channels is not None else self.channels
        self.img_shape = (self.img_height, self.img_width, self.channels)
        self.batch_size = batch_size if batch_size is not None else self.batch_size

        discriminator_optimizer = optimizer if discriminator_optimizer is None else discriminator_optimizer
        if not compile_only:
            self.discriminator = self._build_discriminator()
            self.generator = self._build_generator()

            self.history["D_loss"] = []
            self.history["D_loss_positives"] = []
            self.history["D_loss_negatives"] = []
            self.history["D_loss_dummies"] = []
            self.history["G_loss"] = []

        for layer in self.generator.layers:
            layer.trainable = False
        self.generator.trainable = False

        self._build_discriminator_model(optimizer)
        for layer in self.discriminator.layers:
            layer.trainable = False
        self.discriminator.trainable = False
        for layer in self.generator.layers:
            layer.trainable = True
        self.generator.trainable = True
        self._build_combined_model(discriminator_optimizer)

    def _build_discriminator_model(self, optimizer):
        """Builds the discriminator for the WGAN with gradient penalty
        @ TODO
        The discriminator takes real images, generated ones and an average of both and optimizes the wasserstein loss
        for the real and the fake images as well as the gradient penalty for the averaged samples
        """
        disc_input_image = Input(self.img_shape, name="Img_Input")
        disc_input_noise = Input((self.latent_size,), name="Noise_Input_for_Discriminator")
        gen_image_disc = self.generator(disc_input_noise)
        disc_image_gen = self.discriminator(gen_image_disc)
        disc_image_image = self.discriminator(disc_input_image)
        avg_samples = RandomWeightedAverage(self.batch_size)([disc_input_image, gen_image_disc])
        disc_avg_disc = self.discriminator(avg_samples)
        self.discriminator_model = Model(inputs=[disc_input_image, disc_input_noise],
                                         outputs=[disc_image_image, disc_image_gen, disc_avg_disc])
        partial_gp_loss = functools.partial(gradient_penalty_loss, averaged_samples=avg_samples,
                                            gradient_penalty_weight=self._gradient_penalty_weight)
        partial_gp_loss.__name__ = 'gradient_penalty'
        self.discriminator_model.compile(loss=[wasserstein_loss, wasserstein_loss, partial_gp_loss],
                                         optimizer=optimizer)

    def _build_combined_model(self, optimizer):
        """Build the combined GAN consisting of generator and discriminator
        @ TODO
        Takes the latent input and generates an images out of it by applying the generator. Classifies the image via the
        discriminator. The model is compiled using the given optimizer

        Args:
            optimizer: which optimizer to use
        """
        gen_input_latent = Input((self.latent_size,), name="Latent_Input")
        gen_image = self.generator(gen_input_latent)
        disc_image = self.discriminator(gen_image)
        self.combined_model = Model(gen_input_latent, disc_image)
        self.combined_model.compile(optimizer, loss=[wasserstein_loss])

    def _build_generator(self):
        """
        @TODO
        Returns:

        """
        n_filters = self.latent_size
        cur_resolution = 4
        noise_input = Input((self.latent_size,))
        x = PixelNorm()(noise_input)
        x = ScaledDense(units=4 * 4 * self.latent_size, gain=np.sqrt(2) / 4)(x)
        x = Reshape((4, 4, self.latent_size))(x)
        x = LeakyReLU(0.2)(x)
        x = PixelNorm()(x)

        x = ScaledConv2D(filters=n_filters, kernel_size=(4, 4), strides=(1, 1), padding="same",
                         kernel_initializer=RandomNormal(0, 1))(x)
        x = LeakyReLU(.2)(x)
        x = PixelNorm()(x)
        x = ScaledConv2D(filters=n_filters, kernel_size=(3, 3), strides=(1, 1), padding="same",
                         kernel_initializer=RandomNormal(0, 1))(x)
        x = LeakyReLU(.2)(x)
        x = PixelNorm()(x)

        while cur_resolution < self.img_shape[0]:
            x = UpSampling2D()(x)
            cur_resolution *= 2
            n_filters = self.calc_filters(cur_resolution)
            x = ScaledConv2D(filters=n_filters, kernel_size=(3, 3), strides=(1, 1), padding="same",
                             kernel_initializer=RandomNormal(0, 1))(x)
            x = LeakyReLU(.2)(x)
            x = PixelNorm()(x)
            x = ScaledConv2D(filters=n_filters, kernel_size=(3, 3), strides=(1, 1), padding="same",
                             kernel_initializer=RandomNormal(0, 1))(x)
            x = LeakyReLU(.2)(x)
            x = PixelNorm()(x)

        generator_output = ScaledConv2D(filters=self.channels, kernel_size=(1, 1), strides=(1, 1), padding="same",
                                        kernel_initializer=RandomNormal(0, 1), gain=1, name="to_rgb_removable")(x)
        generator_model = Model(noise_input, generator_output)
        return generator_model

    def _build_discriminator(self):
        """
        @TODO
        Returns:

        """

        cur_resolution = self.img_height
        n_filters = self.calc_filters(cur_resolution)

        image_input = Input(self.img_shape)
        x = ScaledConv2D(filters=n_filters, kernel_size=(1, 1), strides=(1, 1), padding="same",
                         kernel_initializer=RandomNormal(0, 1))(image_input)
        x = LeakyReLU(.2)(x)

        fused_set = False
        while cur_resolution > 4:
            name = "fuse_here" if not fused_set else None
            x = ScaledConv2D(filters=n_filters, kernel_size=(3, 3), strides=(1, 1), padding="same",
                             kernel_initializer=RandomNormal(0, 1), name=name)(x)
            fused_set = True
            x = LeakyReLU(.2)(x)
            cur_resolution //= 2
            n_filters = self.calc_filters(cur_resolution)
            x = ScaledConv2D(filters=n_filters, kernel_size=(3, 3), strides=(1, 1), padding="same",
                             kernel_initializer=RandomNormal(0, 1))(x)
            x = LeakyReLU(.2)(x)
            x = AveragePooling2D(2, 2)(x)

        name = "fuse_here" if self.img_shape[0] == 4 else None
        x = MinibatchSd(name=name)(x)
        x = ScaledConv2D(filters=n_filters, kernel_size=(3, 3), strides=(1, 1), padding="same",
                         kernel_initializer=RandomNormal(0, 1))(x)
        x = LeakyReLU(.2)(x)
        x = ScaledConv2D(filters=n_filters, kernel_size=(4, 4), strides=(4, 4), padding="same",
                         kernel_initializer=RandomNormal(0, 1))(x)
        x = LeakyReLU(.2)(x)

        x = Flatten()(x)
        x = ScaledDense(units=1, gain=1)(x)

        discriminator_model = Model(image_input, x)
        return discriminator_model

    def train_on_batch(self, real_images, n_critic: int = 5):
        """Runs a single gradient update on a batch of data.
        @ TODO
        Args:
            real_images: numpy array of real input images used for training
            n_critic: number of discriminator updates for each iteration
        """
        batch_size = real_images.shape[0] // n_critic
        real_y = np.ones((batch_size, 1)) * -1

        for i in range(n_critic):
            discriminator_minibatch = real_images[i * batch_size:(i + 1) * batch_size]
            losses = self.train_discriminator(discriminator_minibatch)

        self.history["D_loss"].append(losses[0])
        self.history["D_loss_positives"].append(losses[1])
        self.history["D_loss_negatives"].append(losses[2])
        self.history["D_loss_dummies"].append(losses[3])

        noise = np.random.normal(size=(batch_size, self.latent_size))
        self.history["G_loss"].append(self.combined_model.train_on_batch(noise, real_y))

    def train_discriminator(self, real_images):
        """Runs a single gradient update on a batch of data.
        @ TODO
        Args:
            real_images: numpy array of real input images used for training

        Returns:
            the losses for this training iteration
        """
        batch_size = len(real_images)
        fake_y = np.ones((batch_size, 1))
        real_y = np.ones((batch_size, 1)) * -1
        dummy_y = np.zeros((batch_size, 1), dtype=np.float32)
        noise = np.random.normal(size=(batch_size, self.latent_size))
        losses = self.discriminator_model.train_on_batch([real_images, noise], [real_y, fake_y, dummy_y])
        return losses

    def add_fade_in_layers(self, target_resolution):
        upsampled_old_generator = self._upsample_generator()
        new_generator = self._add_fade_in_layer_to_generator()
        merged = WeightedSum(name="gen_weighted_sum_removable")([upsampled_old_generator, new_generator])
        self.generator = Model(self.generator.inputs, merged)

        image_input = Input((target_resolution, target_resolution, self.channels))
        downsampled_old_discriminator = self._downsample_discriminator(image_input)
        new_discriminator_layer = self._add_fade_in_layer_to_discriminator(image_input)
        x = WeightedSum(name="dist_weighted_sum_removable")([downsampled_old_discriminator, new_discriminator_layer])
        fuse_layer_passed = False
        for layer in self.discriminator.layers:
            if layer.name == "fuse_here":
                fuse_layer_passed = True
            if fuse_layer_passed:
                x = layer(x)
        self.discriminator = Model(image_input, x)

        self.img_shape = (target_resolution, target_resolution, self.channels)
        self.img_height = target_resolution
        self.img_width = target_resolution

    def _add_fade_in_layer_to_generator(self):
        x = self.generator.layers[-2].output
        x = UpSampling2D()(x)

        cur_resolution = x.shape[1].value
        n_filters = self.calc_filters(cur_resolution)

        x = ScaledConv2D(filters=n_filters, kernel_size=(3, 3), strides=(1, 1), padding="same",
                         kernel_initializer=RandomNormal(0, 1))(x)
        x = LeakyReLU(.2)(x)
        x = PixelNorm()(x)
        x = ScaledConv2D(filters=n_filters, kernel_size=(3, 3), strides=(1, 1), padding="same",
                         kernel_initializer=RandomNormal(0, 1))(x)
        x = LeakyReLU(.2)(x)
        x = PixelNorm()(x)

        generator_output = ScaledConv2D(filters=self.channels, kernel_size=(1, 1), strides=(1, 1), padding="same",
                                        kernel_initializer=RandomNormal(0, 1), gain=1)(x)
        return generator_output

    def _upsample_generator(self):
        x = self.generator.layers[-1].output
        x = UpSampling2D(name="upsampling_removable")(x)
        return x

    def _add_fade_in_layer_to_discriminator(self, image_input):
        cur_resolution = image_input.shape[1].value
        n_filters = self.calc_filters(cur_resolution)

        x = ScaledConv2D(filters=n_filters, kernel_size=(1, 1), strides=(1, 1), padding="same",
                         kernel_initializer=RandomNormal(0, 1))(image_input)
        x = LeakyReLU(.2)(x)

        x = ScaledConv2D(filters=n_filters, kernel_size=(3, 3), strides=(1, 1), padding="same",
                         kernel_initializer=RandomNormal(0, 1))(x)
        x = LeakyReLU(.2)(x)
        cur_resolution //= 2
        n_filters = self.calc_filters(cur_resolution)
        x = ScaledConv2D(filters=n_filters, kernel_size=(3, 3), strides=(1, 1), padding="same",
                         kernel_initializer=RandomNormal(0, 1), gain=1)(x)
        x = LeakyReLU(.2)(x)
        x = AveragePooling2D(2, 2)(x)
        return x

    def _downsample_discriminator(self, image_input):
        x = AveragePooling2D(2, 2, name="avg_pool_removable")(image_input)
        scaled_conv2d = self.discriminator.layers[1]
        scaled_conv2d.name = "conv2d_removable"
        lrelu = self.discriminator.layers[2]
        lrelu.name = "lrelu_removable"
        x = scaled_conv2d(x)
        x = lrelu(x)
        return x

    def update_alpha(self, alpha):
        models = [self.generator, self.discriminator, self.discriminator_model, self.combined_model]
        for model in models:
            for layer in model.layers:
                if isinstance(layer, WeightedSum):
                    K.set_value(layer.alpha, alpha)

    def remove_fade_in_layers(self):
        self._remove_fade_in_layer_from_generator()
        self._remove_fade_in_layer_from_discriminator()

    def _remove_fade_in_layer_from_generator(self):
        x = self.generator.inputs[0]
        for layer in self.generator.layers[1:]:
            if "removable" not in layer.name:
                x = layer(x)
        self.generator = Model(self.generator.get_input_at(0), x)

    def _remove_fade_in_layer_from_discriminator(self):
        x = self.discriminator.inputs[0]
        for layer in self.discriminator.layers[1:]:
            if "removable" not in layer.name:
                x = layer(x)
        self.discriminator = Model(self.discriminator.get_input_at(0), x)

    def calc_filters(self, x):
        return int(min((4 * 4 * self.latent_size / x) * 2, self.latent_size))