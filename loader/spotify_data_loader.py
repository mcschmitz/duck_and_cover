from typing import Dict

import numpy as np
import pandas as pd
import pytorch_lightning as pl
import torch
from skimage.io import imread
from skimage.transform import resize
from sklearn.preprocessing import StandardScaler
from torch.utils.data import IterableDataset

from config import GANTrainConfig
from utils import logger
from utils.image_operations import adjust_dynamic_range


class SpotifyDataGenerator(IterableDataset):
    def __init__(
        self,
        meta_df: pd.DataFrame,
        batch_size: int,
        image_size: int,
        return_release_year: bool,
    ):
        """
        Training datagenerator for the Spotify dataset.

        Args:
            meta_df: Meta data Dataframe
            batch_size: Batch size
            image_size: Image size
            return_release_year: Boolean flag to add release year to the batch
        """
        self.meta_df = meta_df
        self.meta_df = self.meta_df.dropna(
            subset=["file_path_64", "file_path_300"]
        )
        self.image_size = image_size
        self.batch_size = batch_size

        self.release_year_scaler = None
        if return_release_year:
            self.meta_df = self.meta_df.dropna(subset=["album_release"])
            self.release_year_scaler = StandardScaler().fit(
                self.meta_df["album_release"].values.reshape(-1, 1)
            )
        self.source_size = 64 if self.image_size <= 64 else 300
        self.files = self.meta_df[f"file_path_{self.source_size}"]
        self.files = self.files.to_list()
        self.n_images = len(self.meta_df)
        self._iterator_i = 0

    def __iter__(self):
        yield from (self[batch_id] for batch_id in range(len(self)))

    def __len__(self):
        return self.n_images // self.batch_size

    def __getitem__(self, item) -> Dict[str, torch.Tensor]:
        batch_x = []
        year_x = []

        batch_idx = self._get_batch_idx()
        for b_idx in batch_idx:
            file_path = self.files[b_idx]
            img = imread(file_path)
            img = np.moveaxis(img, -1, 0)
            img = resize(
                img,
                (3, self.source_size, self.source_size),
                preserve_range=True,
            )
            batch_x.append(img)
            if self.release_year_scaler is not None:
                year = [[self.meta_df["album_release"][b_idx]]]
                year = self.release_year_scaler.transform(year)
                year_x.append(year.flatten())
        self._iterator_i = batch_idx[-1]
        images = torch.Tensor(np.array(batch_x))
        images = adjust_dynamic_range(
            images, drange_in=(0, 255), drange_out=(-1, 1)
        )
        year = torch.Tensor(np.array(year_x)) if year_x else None
        return {"images": images, "year": year}

    def _get_batch_idx(self):
        positions = np.arange(
            self._iterator_i, self._iterator_i + self.batch_size
        )
        batch_idx = [
            i if i < self.n_images else i - self.n_images for i in positions
        ]
        if 0 in batch_idx:
            logger.info("Data Generator exceeded. Will shuffle input data.")
            self.meta_df = self.meta_df.sample(frac=1).reset_index(drop=True)
            self.files = (
                self.meta_df["file_path_64"]
                if self.image_size <= 64
                else self.meta_df["file_path_300"]
            )
            self.files = self.files.to_list()
        return batch_idx


class SpotifyDataloader(pl.LightningDataModule):
    def __init__(self, config: GANTrainConfig):
        """
        Dataloader for the Spotify Dataset.

        Args:
            config: Training configuration.
        """
        super().__init__()
        self.config = config
        self.meta_df = pd.read_json(
            self.config.meta_data_path, orient="records", lines=True
        )
        self.spotify_train = None

    def set_image_size(self, image_size: int):
        self.spotify_train = SpotifyDataGenerator(
            meta_df=self.meta_df,
            batch_size=self.config.batch_size[image_size],
            image_size=image_size,
            return_release_year=self.config.add_release_year,
        )

    def train_dataloader(self) -> SpotifyDataGenerator:
        """
        Returns the dataloader.
        """
        return self.spotify_train
