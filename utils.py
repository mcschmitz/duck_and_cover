import logging
import os
import re
from datetime import datetime

import imageio
import numpy as np
import psutil
import seaborn as sns
from matplotlib import pyplot as plt
from matplotlib.animation import ArtistAnimation
from skimage.io import imread
from skimage.transform import resize
from tensorflow.keras import backend as K
from tensorflow.keras.preprocessing.image import array_to_img
from tqdm import tqdm

from constants import LOG_DATETIME_FORMAT, LOG_FORMAT, LOG_LEVEL

logging.basicConfig(
    format=LOG_FORMAT, datefmt=LOG_DATETIME_FORMAT, level=LOG_LEVEL
)
logger = logging.getLogger(__file__)

plt.ioff()


def create_dir(directory_path: str) -> str:
    """
    Creates a directory to the given path if it does not exist and returns the
    path.

    Args:
        directory_path: path directory

    Returns:
        the created path
    """
    if not os.path.exists(directory_path):
        os.makedirs(directory_path)
    return directory_path


def generate_images(
    generator_model,
    output_dir: str,
    n_imgs: int = 10,
    seed: int = None,
    target_size: tuple = (64, 64),
):
    """
    Generates a list of images by predicting with the given generator.

    Feeds normal distributed random numbers into the generator to generate
    `n_imgs`, tiles the image, rescales it and and saves the output to a PNG
    file.

    Args:
        generator_model: Generator used for generating the images
        output_dir: where to save the results
        n_imgs: number of images to generate
        seed: seed to use to generate the numbers of the latent space
        target_size: target size of the image
    """
    if seed is not None:
        np.random.seed(seed)
    else:
        np.random.seed()

    idx = 1
    figsize = (np.array(target_size) * [10, n_imgs]).astype(int)
    plt.figure(figsize=figsize, dpi=1)
    for _i in range(n_imgs):
        x0 = np.random.normal(size=generator_model.input_shape[1])
        x1 = np.random.normal(size=generator_model.input_shape[1])
        x = np.linspace(x0, x1, 10)
        generated_images = generator_model.predict(x)
        for img in generated_images:
            img = array_to_img(img, scale=True)
            img = img.resize(size=target_size)
            plt.subplot(n_imgs, 10, idx)
            plt.axis("off")
            plt.imshow(img)
            idx += 1
            plt.subplots_adjust(
                left=0, bottom=0, right=1, top=1, wspace=0, hspace=0.1
            )
    plt.savefig(output_dir, dpi=1)
    plt.close()


class AnimatedGif(object):
    def __init__(self, size: tuple = (640, 480)):
        """
        Allows the addition and generation of gifs by adding multiple images.

        Args:
            size: Final size of the gif

        Refs https://tomroelandts.com/articles/how-to-create-animated-gifs-with-python
        """
        self.size = size
        self.fig = plt.figure()
        self.fig.set_size_inches(self.size[0] / 100, self.size[1] / 100)
        ax = self.fig.add_axes([0, 0, 1, 1], frameon=False, aspect=1)
        ax.set_xticks([])
        ax.set_yticks([])
        self.images = []

    def add(self, image, label="", label_position: tuple = (1, 1)):
        """
        Add an image to thhe gif.

        Args:
            image: Imported image
            label: Label of the image. Will be added to the given position
            label_position: Label position
        """
        plt_im = plt.imshow(image, vmin=0, vmax=1, animated=True)
        plt_txt = plt.text(
            label_position[0],
            label_position[1],
            label,
            color="black",
            fontsize=20,
        )
        self.images.append([plt_im, plt_txt])

    def save(self, filename, fps: float = 10):
        """
        Save Gif.

        Args:
            filename: Filename of the Gif
            fps: Frames per second
        """
        animation = ArtistAnimation(self.fig, self.images)
        animation.save(filename, writer="imagemagick", fps=fps)


def load_data(path: str, size: int = 4):
    """
    Loads the image dataset.

    Args:
        path: path to the image files
        size: target resolution of the image tensor

    Returns:
        list of image tensor and image index
    """
    np_path = os.path.join(path, "all{0}.npy".format(size))
    np_path_exists = os.path.exists(np_path)
    sys_memory80 = psutil.virtual_memory().total * 0.8
    if np_path_exists and os.stat(np_path).st_size < sys_memory80:
        images = np.load(np_path)
        img_idx = np.arange(0, images.shape[0])
        return images, img_idx
    elif np_path_exists:
        logger.info(
            "Data does not fit inside memory. Won't preallocate but iterate"
        )
    else:
        try:
            files = []
            for dirpath, _dirnames, filenames in os.walk(path):
                for filename in [f for f in filenames if f.endswith(".jpg")]:
                    files.append(os.path.join(dirpath, filename))
            images = np.zeros((len(files), size, size, 3), dtype=K.floatx())

            for i, file_path in tqdm(enumerate(files)):
                img = imread(file_path)
                img = resize(img, (size, size, 3))
                img = scale_images(img)
                images[i] = img
            np.save(np_path, images)
            img_idx = np.arange(0, images.shape[0])
            return images, img_idx
        except MemoryError:
            logger.error("Data does not fit inside Memory. Can't preallocate.")


def scale_images(images: np.array):
    """
    Scales the images to [-1, 1]

    Args:
        images: numpy array of images

    Returns:
        The scaled images as numpy array
    """
    images = (images - 127.5) / 127.5
    return images


def resize_images(images: np.array, new_shape: tuple):
    """
    Scales images to desired size.

    Args:
        images: List of images
        new_shape: Tuple of the desired image size
    """
    images_list = list()
    for image in tqdm(images):
        new_image = resize(image, new_shape, 0)
        images_list.append(new_image)
    return np.asarray(images_list)


def plot_metric(path, steps, metric, **kwargs):
    """
    @TODO
    Args:
        path:
        steps:
        metric:

    Returns:

    """
    x_axis = np.linspace(0, steps, len(metric))
    sns.lineplot(x_axis, metric)
    plt.ylabel(kwargs.get("y_label", ""))
    plt.xlabel(kwargs.get("x_label", "Images shown"))
    plt.savefig(
        os.path.join(path, kwargs.get("file_name", hash(datetime.now())))
    )
    plt.close()


def plot_final_gif(path: str):
    gif_size = (256 * 10, 256)
    for s in range(25):
        images = []
        labels = []
        for root, dirs, files in os.walk(path):
            for file in files:
                if file.startswith(f"{s}_fixed_step_gif"):
                    images.append(imageio.imread(os.path.join(root, file)))
                    labels.append(int(re.findall("\d+", file)[1]))
        order = np.argsort(labels)
        images = [images[i] for i in order]
        labels = [labels[i] for i in order]
        animated_gif = AnimatedGif(size=gif_size)
        for img, lab in zip(images, labels):
            animated_gif.add(
                img,
                label="{} Images shown".format(lab),
                label_position=(10, gif_size[1] * 0.95),
            )
        animated_gif.save(
            os.path.join(path, f"{s}_fixed.gif"), fps=len(images) / 30
        )
