import datetime
import time
from plexapi.exceptions import Unauthorized
import requests
from utils import logger, deconvert_imdb_id, update_many
from bs4 import BeautifulSoup
from db_tools import get_my_imdb_users, get_my_movies, get_watchlist_intersections
from plex_utils import get_user_watched_movies
import re
import pandas as pd
from settings import MY_IMDB_REFRESH_INTERVAL


def sync_my_imdb():
    logger.info("Getting users")
    users = get_my_imdb_users()
    for user in users:
        logger.info(f"Syncing data for {user['email']}")
        # Get movies already in DB
        already_in_my_movies = get_my_movies(user['email'])
        # Sync IMDB data
        if user['imdb_id']:
            imdb_data = get_my_imdb(user['imdb_id'])
            imdb_data = [{'imdb_id': deconvert_imdb_id(key), 'my_score': val['rating'], 'seen_date': val['date'],
                          'user': user['email']} for key, val in imdb_data.items() if key not in already_in_my_movies]
            update_many(imdb_data, 'my_movies')

        already_in_my_movies = get_my_movies(user['email'])
        # Sync PLEX data
        try:
            plex_data = get_user_watched_movies(user['email'])
        except Unauthorized:
            logger.error(f"Error retrieving PLEX data for user {user['email']}, unauthorised")
            plex_data = None
        if plex_data:
            plex_data = [x for x in plex_data if x['imdb_id'] not in already_in_my_movies]
            for item in plex_data:
                item['user'] = user['email']
            update_many(plex_data, 'my_movies')
        # Sync IMDB Watchlist
        if user['scan_watchlist'] == 1:
            sync_watchlist(user['imdb_id'])
        logger.info("Done.")


def run_imdb_sync():
    """
    Imports all scores and seen dates from MY_IMDB to our DB
    Adds watchlisted movies to DB in order to be picked up and searched for.
    :return:
    """
    while True:
        sync_my_imdb()
        logger.info(f"Sleeping {MY_IMDB_REFRESH_INTERVAL} minutes...")
        time.sleep(MY_IMDB_REFRESH_INTERVAL * 60)


def get_my_imdb(profile_id):
    try:
        url = 'https://www.imdb.com/user/ur{0}/ratings'.format(profile_id)
        soup_imdb = BeautifulSoup(requests.get(url).text, 'html.parser')
        titles = int(soup_imdb.find('div', class_='lister-list-length').find('span',
                                                                             id='lister-header-current-size').get_text().replace(
            ',', ''))
        pages = int(titles / 100) + 1

        results = {}
        for page in range(pages + 1):
            ids = soup_imdb.findAll('div', {'class': 'lister-item-image ribbonize'})
            ratings = soup_imdb.findAll('div', {'class': 'ipl-rating-star ipl-rating-star--other-user small'})
            dates = []

            for y in soup_imdb.findAll('p', {'class': 'text-muted'}):
                if str(y)[:30] == '<p class="text-muted">Rated on':
                    date = re.search('%s(.*)%s' % ('Rated on ', '</p>'), str(y)).group(1)
                    dates.append(date)
            try:
                last_page = False
                next_url = soup_imdb.find('a', {'class': 'flat-button lister-page-next next-page'})['href']
            except:
                last_page = True
            for x, y, z in zip(ids, ratings, dates):
                imdb_id = x['data-tconst']
                rating = int(y.get_text())
                date = datetime.datetime.strptime(z, '%d %b %Y')
                date = date.strftime('%Y-%m-%d')
                results.update({imdb_id: {'rating': rating, 'date': date}})
            if not last_page:
                next_url = 'https://www.imdb.com{0}'.format(next_url)
                soup_imdb = BeautifulSoup(requests.get(next_url).text, 'html.parser')

        return results

    except Exception as e:
        logger.error(f"Could not fetch MyIMDB for user {profile_id}, error: {e}")
        return None


def get_my_watchlist(profile_id):
    try:
        url = f'https://www.imdb.com/user/ur{profile_id}/watchlist'
        soup_imdb = BeautifulSoup(requests.get(url).text, 'html.parser')
        listId = soup_imdb.find("meta", property="pageId")['content']
        url = f"https://www.imdb.com/list/{listId}/export"
        df = pd.read_csv(url)
        # Return only movies
        return df.loc[df['Title Type'] == 'movie']['Const'].tolist()
    except Exception as e:
        logger.error(f"Can't fetch IMDB Watchlist for user {profile_id}, error: {e}")
        return None


def sync_watchlist(profile_id):
    # TODO check if movie already in torrent database and mark it if it is, also exclude quality
    logger.info(f"Syncing watchlist for user {profile_id}")
    try:
        watchlist = get_my_watchlist(profile_id)
        watchlist = [int(deconvert_imdb_id(x)) for x in watchlist]
        already_processed = get_watchlist_intersections(profile_id, watchlist)
        watchlist = [{
            'movie_id': x,
            'imdb_id': profile_id,
            'status': 'new',
        } for x in watchlist if x not in already_processed]
        update_many(watchlist, 'watchlists')
    except Exception as e:
        logger.error(f"Watchlist sync for user {profile_id} failed. Error: {e}")
    logger.info("Done.")


if __name__ == '__main__':
    # x = get_my_watchlist(77571297)
    # sync_watchlist(77571297)
    run_imdb_sync()
