import os
from datetime import datetime

from apscheduler.events import EVENT_JOB_EXECUTED, EVENT_JOB_SUBMITTED
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.schedulers.blocking import BlockingScheduler

from refresh_imdb_db import update_imdb_db
from refresh_omdb_db import get_omdb_data
from refresh_tmdb_db import get_tmdb_data
from utils import setup_logger, DB_URI, check_movielib_database

# ENV variables
TZ = os.getenv('TZ')
IMDB_DB_REFRESH_INTERVAL = int(os.getenv('IMDB_DB_REFRESH_INTERVAL'))
MYIMDB_REFRESH_INTERVAL = int(os.getenv('MYIMDB_REFRESH_INTERVAL'))


logger = setup_logger("MasterScheduler_MOVIELIB")

jobstores = {
    'default': SQLAlchemyJobStore(url=DB_URI)
}


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


def at_execution_finish(event):
    if event.job_id == 'update_imdb_db':
        logger.info("IMDB refresh finished. Resuming the other jobs...")
        # Resume TMDB
        try:
            scheduler.resume_job(job_id='get_tmdb_data')
            logger.info(f"Job get_tmdb_data resumed.")
        except IndexError:
            logger.warning(f"No job to resume: get_tmdb_data")
        # Resume OMDB
        try:
            scheduler.resume_job(job_id='get_omdb_data')
            logger.info(f"Job get_omdb_data resumed.")
        except IndexError:
            logger.warning(f"No job to resume: get_omdb_data")


def at_job_start(event):
    if event.job_id == 'update_imdb_db':
        logger.info("Update IMDB job started, halting the other jobs...")
        # Pause TMDB
        try:
            scheduler.pause_job(job_id='get_tmdb_data')
            logger.info(f"Job get_tmdb_data paused until IMDB refresh is completed.")
        except IndexError:
            logger.warning(f"No job to pause: get_tmdb_data")
        # Pause OMDB
        try:
            scheduler.pause_job(job_id='get_omdb_data')
            logger.info(f"Job get_omdb_data paused until IMDB refresh is completed.")
        except IndexError:
            logger.warning(f"No job to pause: get_omdb_data")


if __name__ == '__main__':
    scheduler = BlockingScheduler(jobstores=jobstores, timezone=TZ)

    try:
        scheduler.add_job(update_imdb_db, 'cron', day=1, hour=1, id='update_imdb_db', coalesce=True,
                          misfire_grace_time=3000000, replace_existing=True)
        scheduler.add_job(get_tmdb_data, 'interval', hours=1, id='get_tmdb_data', coalesce=True,
                          misfire_grace_time=3000000, replace_existing=True, next_run_time=datetime.now())
        scheduler.add_job(get_omdb_data, 'interval', hours=1, id='get_omdb_data', coalesce=True,
                          misfire_grace_time=3000000, replace_existing=True, next_run_time=datetime.now())
        scheduler.add_job(info_jobs, 'interval', minutes=30, id='info', coalesce=True, next_run_time=datetime.now(),
                          misfire_grace_time=3000000, replace_existing=True)



        scheduler.add_listener(at_job_start, EVENT_JOB_SUBMITTED)
        scheduler.add_listener(at_execution_finish, EVENT_JOB_EXECUTED)
    except:
        # Means they're already in the database
        scheduler = BlockingScheduler(jobstores=jobstores, timezone=TZ)
        scheduler.add_listener(at_job_start, EVENT_JOB_SUBMITTED)
        scheduler.add_listener(at_execution_finish, EVENT_JOB_EXECUTED)

    if not check_movielib_database():
        update_db_job = scheduler.get_job(job_id='update_imdb_db')
        update_db_job.modify(next_run_time=datetime.now())

    scheduler.start()