# **Duck and Cover**

<div align="center">
  <img src="http://cbarks.dk/Digital/seraa196208.JPG">
  <figcaption>Source: http://cbarks.dk/Digital/seraa196208.JPG</figcaption>
</div>

**Duck and Cover allows you to create your own album covers based on
additional information like the genre of the LP, the release year and the 
name and titles of your artificial album..**

Duck and Cover uses data from more than 600.000 covers of over 120.000
spotify top artists from 3.254 genres to learn about the structure and
appearance of let's say a thrash metal album cover from 1988.

### Data Gathering
Data gathering consists of two steps:
1. Create a `.env` file with your `SPOTIPY_CLIENT_ID` and 
   `SPOTIPY_CLIENT_SECRET` (Spotify API Client ID & Secret). Read more on 
   how to get your Spotify client ID and secret [here](https://developer.spotify.com/documentation/general/guides/app-settings/).
2. Run the [data collection script](data_collection/collect_artist_data.py) 
   which iteratively collects the top 50 artists for each of the genres 
   listed in [this file](data/genres.txt) and their related artists whereby 
   duplicated artists are removed. After this step the script builds a table containing genre and release date of each album released by these artists, the artists and the album name as well as an URL to download a 300x300 as well as a 64x64 image of the cover. Based on this URL the covers are finally downloaded and save to a unified identifiable file structure.
   
 All of the final and intermediate results of the tasks in steps in 2. are saved in a temporary dictionary to allow splitting the data collection in case of reaching the quota limit of the Spotify API (which is usually not the case) or running into other trouble.
 
### Networks and results
The first network built is a simple [Deep Convolutional GAN](https://arxiv.org/pdf/1511.06434.pdf). The results aren't really satisfying since a DCGAN is not able to capture
the manifold variations in an album Cover and collapses pretty early on:

<div align="center">
  <img src="img/learning_progress_gan.gif">
</div>

Switching from a normal binary crossentropy loss for both discriminator and 
the combined model to a [GAN trained with wasserstein loss fused with 
gradient penalty](https://arxiv.org/pdf/1704.00028.pdf) yields much better results than the DCGAN:

<div align="center">
  <img src="img/learning_progress_wgan.gif">
</div>

Obviously optimizing the wasserstein loss results in more stable gradients which leads to a steady learning phase, whereas the gradient penalty prevents varnished gradients. This results in a detectable structure in the generated images, so that they even adumbrate interpret or album names on top or bottom of the generated covers.

Now let's have a look at the results of the ProGAN. Clearly once can see how the model is built up from a very small resolution to a final resolution of 512x512 pixel. This allows the network to learn the structure of the image little by little and produces an image that has clearer edges on those structures. The results are far from perfect, but much better than on the Deep Convolutional GAN and on the Wassertrein GAN.

<div align="center">
  <img src="img/learning_progress_progan.gif">
</div>

### Next Steps:
1. Train ProGan + Genre
2. Integrate Artist Name
3. Integrate Album Name
4. Migrate W-GAN to PTLightning
5. Migrate DCGAN to PTLightning