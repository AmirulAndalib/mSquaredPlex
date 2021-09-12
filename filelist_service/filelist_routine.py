import os
from datetime import datetime

import requests
from apscheduler.schedulers.blocking import BlockingScheduler

from email_tools import send_email
from utils import torr_cypher, get_movie_details, setup_logger, timing, check_against_my_torrents, \
    check_database

TZ = os.getenv('TZ')
API_URL = os.getenv('API_URL')
USER = os.getenv('USER')
PASSKEY = os.getenv('PASSKEY')
MOVIE_HDRO = os.getenv('MOVIE_HDRO')
MOVIE_4K = os.getenv('MOVIE_4K')
FILELIST_ROUTINE_TIMES = os.getenv('FILELIST_ROUTINE_TIMES')
FILELIST_ROUTINE_TIMES = FILELIST_ROUTINE_TIMES.split(',')

logger = setup_logger("FilelistRoutine")


# https://filelist.io/forums.php?action=viewtopic&topicid=120435

def check_in_my_torrents(torrents):
    new_torrents = []
    already_in_db = check_against_my_torrents(torrents)
    already_in_db = [x['torr_id'] for x in already_in_db] if already_in_db else []
    for torrent in torrents:
        if torrent['id'] not in already_in_db:
            new_torrents.append(torrent)
    return new_torrents


def retrieve_bulk_from_dbs(items):
    logger.info("Getting IMDB TMDB and OMDB metadata...")
    return [get_movie_details(item) for item in items]


def get_latest_torrents(n=10, category=MOVIE_HDRO):
    """
    returns last n movies from filelist API.
    n default 100
    movie category default HD RO
    """
    logger.info('Getting RSS feeds')
    r = requests.get(
        url=API_URL,
        params={
            'username': USER,
            'passkey': PASSKEY,
            'action': 'latest-torrents',
            'category': category,
            'limit': n,
        },
    )
    if category == MOVIE_4K:
        return [x for x in r.json() if 'Remux' in x['name']]
    logger.info(f"Got {len(r.json())} new torrents")
    return r.json()


@timing
def feed_routine(cypher=torr_cypher):
    # fetch latest movies
    new_movies = get_latest_torrents()

    # filter out those already in database with same or better quality and mark
    # the rest if they are already in db
    new_movies = check_in_my_torrents(new_movies)

    # get IMDB, TMDB and OMDB data for these new movies.
    new_movies = retrieve_bulk_from_dbs(new_movies)

    # send to user to choose
    send_email(new_movies, cypher)


def info_jobs():
    jobs = scheduler.get_jobs()
    logger.info(f"Found {len(jobs)} in this scheduler.")
    for job in scheduler.get_jobs():
        message = f"Job {job.name} with the general trigger {job.trigger}"
        if job.pending:
            message += f" is yet to be added to the jobstore, no next run time yet."
        else:
            message += f" will run next on {job.next_run_time}"
        logger.info(message)


if __name__ == '__main__':
    check_database()

    scheduler = BlockingScheduler(timezone=TZ)

    for hour in FILELIST_ROUTINE_TIMES:
        scheduler.add_job(feed_routine, 'cron', hour=int(hour), id=f"Filelist Routine {hour} o'clock",
                          coalesce=True, misfire_grace_time=3000000, replace_existing=True)

    scheduler.add_job(info_jobs, 'interval', minutes=30, id='Filelist RoutineInfo', coalesce=True,
                      next_run_time=datetime.now(), misfire_grace_time=3000000, replace_existing=True)

    scheduler.start()
