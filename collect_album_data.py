import json

import spotipy
import spotipy.util as util
import tqdm

from spotify_client import get_client_id, get_client_secret


def generate_spotify_session(token):
    return spotipy.Spotify(token)


def get_artist_album_data(artists: dict, token: str):
    """
    Collects information about all albums released by a list of artists

    """
    spotify_session = generate_spotify_session(token)
    for idx, artist_id in tqdm.tqdm(enumerate(artists)):
        album_data = spotify_session.artist_albums(artist_id, album_type="album", limit=50)["items"]
        if len(album_data) > 0:
            artists[artist_id]["albums"] = {}
            for album in album_data:

                if not album["images"]:
                    continue
                else:
                    images = album["images"]
                    cover_url = [i["url"] for i in images if i["height"] == 300]
                    if len(cover_url) > 0:
                        release_year = int(album["release_date"][:4])
                        artists[artist_id]["albums"][album["id"]] = {"release_year": release_year,
                                                                     "cover_url": cover_url, "name": album["name"]}
        if idx % 1000 == 0:
            spotify_session = generate_spotify_session(token)
        if idx % 10000 == 0:
            token = util.oauth2.SpotifyClientCredentials(client_id=client_id,
                                                         client_secret=client_secret).get_access_token()

    artists_to_remove = [i for i in artists if len(artists[artist_id]["albums"]) == 0]
    for artist_id in artists_to_remove:
        del artists[artist_id]
    return artists


if __name__ == "__main__":
    client_id = get_client_id()
    client_secret = get_client_secret()

    token = util.oauth2.SpotifyClientCredentials(client_id=client_id, client_secret=client_secret).get_access_token()
    genres = [line.rstrip("\n") for line in open("data/genres.txt")]

    with open("data/artist_album_data.json", "r", encoding="utf-8") as file:
        artists = json.load(file)

    artists = get_artist_album_data(artists, token)
    with open("data/artist_album_data.json", "w", encoding="utf-8") as file:
        json.dump(artists, file)