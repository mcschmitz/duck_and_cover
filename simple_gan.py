import matplotlib.pyplot as plt
import pandas as pd
import seaborn as sns

from Loader.cover_loader import ImageLoader
from Networks.simple_gan import DaCSimple
from utils import create_dir, generate_images

BATCH_SIZE = 128
EPOCH_NUM = 100
PATH = "simple_gan"
image_size = 64
image_ratio = (1, 1)

#  TODO Use Wasserstein Loss
#  TODO Add Release Year information
#  TODO Add Genre Information
#  TODO Let GAN grow

covers = pd.read_json("data/album_data_frame.json", orient="records", lines=True)

data_loader = ImageLoader(data=covers, root="data/covers", batch_size=BATCH_SIZE, image_size=image_size,
                          image_ratio=image_ratio)
steps_per_epoch = len(covers) // BATCH_SIZE

image_width = data_loader.image_shape[0]
image_height = data_loader.image_shape[1]

dac = DaCSimple(img_width=image_width, img_height=image_height, latent_size=128)
dac.build_models()
d_acc = []
g_loss = []

create_dir("learning_progress/simple_gan")
i = 0
for epoch in range(0, EPOCH_NUM):
    for step in range(0, steps_per_epoch):
        step += 1
        images = data_loader.next()
        cum_d_acc, cum_g_loss = dac.train_on_batch(images)
        print('Epoch {0}: Batch {1}/{2} - Generator Loss: {3:3,.3f} - Discriminator Acc.: {4:3,.3f}'.format(
            dac.adversarial_model.n_epochs + 1, step, steps_per_epoch, cum_g_loss, cum_d_acc))
        if step % 1000 == 0 or step == (steps_per_epoch - 1):
            generate_images(dac.generator,
                            'learning_progress/{}/epoch{}_{}.png'.format(PATH, dac.adversarial_model.n_epochs, step))
    dac.adversarial_model.n_epochs += 1
    dac.reset_metrics()

    d_acc.append(cum_d_acc)
    ax = sns.lineplot(range(dac.adversarial_model.n_epochs), d_acc)
    plt.ylabel('Discriminator Accucary')
    plt.xlabel('Epochs')
    plt.savefig('learning_progress/{}/d_acc.png'.format(PATH))
    plt.close()

    g_loss.append(cum_g_loss)
    ax = sns.lineplot(range(dac.adversarial_model.n_epochs), g_loss)
    plt.ylabel('Generator Loss')
    plt.xlabel('Epochs')
    plt.savefig('learning_progress/{}/g_loss.png'.format(PATH))
    plt.close()