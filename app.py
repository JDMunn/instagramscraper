#!/usr/bin/python
# -*- coding: utf-8 -*-

import argparse
import errno
import json
import logging.config
import os
import re
import time
import warnings

import concurrent.futures
import requests
import tqdm

import time

from constants import *

warnings.filterwarnings('ignore')

class InstagramScraper(object):

    """InstagramScraper scrapes and downloads an instagram user's photos and organizes them by their dank rank"""

    def __init__(self, usernames, login_user=None, login_pass=None, dst=None, quiet=False):
        self.usernames = usernames if isinstance(usernames, list) else [usernames]
        self.login_user = login_user
        self.login_pass = login_pass
        self.dst = './' if dst is None else dst

        # Controls the graphical output of tqdm
        self.quiet = quiet

        # Set up a file logger.
        self.logger = InstagramScraper.get_logger(level=logging.DEBUG)

        self.session = requests.Session()
        self.cookies = None
        self.logged_in = False

        if self.login_user and self.login_pass:
            self.login()

    def login(self):
        """Logs in to instagram"""
        self.session.headers.update({'Referer': BASE_URL})
        req = self.session.get(BASE_URL)

        self.session.headers.update({'X-CSRFToken': req.cookies['csrftoken']})

        login_data = {'username': self.login_user, 'password': self.login_pass}
        login = self.session.post(LOGIN_URL, data=login_data, allow_redirects=True)
        self.session.headers.update({'X-CSRFToken': login.cookies['csrftoken']})
        self.cookies = login.cookies

        if login.status_code == 200 and json.loads(login.text)['authenticated']:
            self.logged_in = True
        else:
            self.logger.exception('Login failed for ' + self.login_user)
            raise ValueError('Login failed for ' + self.login_user)

    def logout(self):
        """Logs out of instagram"""
        if self.logged_in:
            try:
                logout_data = {'csrfmiddlewaretoken': self.cookies['csrftoken']}
                self.session.post(LOGOUT_URL, data=logout_data)
                self.logged_in = False
            except requests.exceptions.RequestException:
                self.logger.warning('Failed to log out ' + self.login_user)

    def make_dst_dir(self, username):
        '''Creates the destination directory'''
        if self.dst == './':
            dst = './' + username
        else:
            dst = self.dst

        if not os.path.exists(dst):
            os.makedirs(dst)

        return dst

    def scrape(self):
        """Crawls through and downloads user's media"""

        # Establishes a thread pool
        executor = concurrent.futures.ThreadPoolExecutor(max_workers=10)

        # Instantiates array to store picture information in
        memes = []

        for username in self.usernames:

            future_to_item = {}
        
            # Get the user metadata.
            user = self.fetch_user(username)


            folls = float(user['followed_by']['count']) 


            # Crawls the media and sends it to the executor.
            for item in tqdm.tqdm(self.media_gen(username), desc='Searching {0} for posts'.format(username), 
                                unit=' media', disable=self.quiet):

                #print "This is a " + str(item.get('type'))

                timeDiff = time.time() - int(item['created_time'])


                # If media is a photo posted within the last 24 hours then scrape
                if timeDiff <= 86400 and str(item.get('type')) == "image":
                    likes = float(item['likes']['count'])

                    comments = float(item['comments']['count'])

                    item['numFollowers'] = folls

                    for key in item:
                        print "key = " + str(key) + " value = " + str(item[key])

                    item['dRank'] = self.dankRank(folls, likes, comments)

                    # Photos added to database by their dank rank
                    if len(memes) != 0:

                        if item['dRank'] > memes[0]['dRank']:
                            memes.insert(0, item)
                        else: memes.append(item)

                    else:
                        memes.append(item)


                else:
                    break

            # Displays the progress bar of completed downloads. Might not even pop up if all media is downloaded while
            # the above loop finishes.
            for future in tqdm.tqdm(concurrent.futures.as_completed(future_to_item), total=len(future_to_item),
                                 desc='Processing', disable=self.quiet):
                item = future_to_item[future]

                if future.exception() is not None:
                     self.logger.warning('Media id {0} at {1} generated an exception: {2}'.format(item['id'], item['url'], future.exception()))


        #stores the 10 dankest memes by dank rank in one folder and their json data in another folder
        memeInfo = {}
        memeInfo['rank'] = {}
        x = 0

        # Destination dir then make destination directory for the dankest to be downloaded
        if self.dst == 'dank': 
            dst = self.make_dst_dir('The Daily Dank')
    
        while x < 10 and x < len(memes):

            #json dict that stores the image's url, account, number followers, number likes, number comments, and dank rank 
            memeInfo['rank'][x+1] = {"url":str(memes[x]['url']),"pageLink":str(memes[x]['link']), 
                                "insta":str(memes[x]['user']['username']), 
                                "numFollowers":memes[x]['numFollowers'], 
                                "numLikes":memes[x]['likes']['count'], 
                                "numComments":memes[x]['comments']['count'], 
                                "dankRank":memes[x]['dRank']
                             }

            if self.dst == 'dank': 
                future = executor.submit(self.download, memes[x] , 'The Daily Dank')
                future_to_item[future] = memes

            x += 1

        with open('theDanks.json', 'w') as fp:
                json.dump(memeInfo, fp)

        self.logout()

    #dank rank alogirthm that specifies how "dank" or popular a meme has the potential to be
    #slutz - number of followers, boners - number of like dem boners 
    def dankRank(self, slutz, boners, numComments):

        if numComments > 0 and boners > 0:
            return .6 * (boners/slutz) * .4 * (numComments/slutz)
        else:
            return 0

    def fetch_user(self, username):
        """Fetches the user's metadata"""
        resp = self.session.get(BASE_URL + username)

        if resp.status_code == 200 and '_sharedData' in resp.text:
            shared_data = resp.text.split("window._sharedData = ")[1].split(";</script>")[0]

            return json.loads(shared_data)['entry_data']['ProfilePage'][0]['user']

    def fetch_stories(self, user_id):
        """Fetches the user's stories"""
        resp = self.session.get(STORIES_URL.format(user_id), headers={
            'user-agent' : STORIES_UA,
            'cookie'     : STORIES_COOKIE.format(self.cookies['ds_user_id'], self.cookies['sessionid'])
        })

        retval = json.loads(resp.text)

        if resp.status_code == 200 and 'items' in retval and len(retval['items']) > 0:
            return [self.set_story_url(item) for item in retval['items']]
        return []

    def media_gen(self, username):
        """Generator of all user's media"""
        try:
            media = self.fetch_media_json(username, max_id=None)

            while True:
                for item in media['items']:
                    yield item
                if media.get('more_available'):
                    max_id = media['items'][-1]['id']
                    media = self.fetch_media_json(username, max_id)
                else:
                    return
        except ValueError:
            self.logger.exception('Failed to get media for ' + username)

    def fetch_media_json(self, username, max_id):
        """Fetches the user's media metadata"""
        url = MEDIA_URL.format(username)

        if max_id is not None:
            url += '?&max_id=' + max_id

        resp = self.session.get(url)

        if resp.status_code == 200:
            media = json.loads(resp.text)

            if not media['items']:
                raise ValueError('User {0} is private'.format(username))

            media['items'] = [self.set_media_url(item) for item in media['items']]
            return media
        else:
            raise ValueError('User {0} does not exist'.format(username))

    def set_media_url(self, item):
        """Sets the media url"""
        item['url'] = item[item['type'] + 's']['standard_resolution']['url'].split('?')[0]
        # remove dimensions to get largest image
        item['url'] = re.sub(r'/s\d{3,}x\d{3,}/', '/', item['url'])
        return item

    def set_story_url(self, item):
        """Sets the story url"""
        item['url'] = item['image_versions2']['candidates'][0]['url'].split('?')[0]
        return item

    def download(self, item, save_dir='./'):
        """Downloads the media file"""
        

        print "_______"

        base_name = item['url'].split('/')[-1]
        file_path = os.path.join(save_dir, base_name)

        if not os.path.isfile(file_path):
            with open(file_path, 'wb') as media_file:
                try:
                    content = self.session.get(item['url']).content
                except requests.exceptions.ConnectionError:
                    time.sleep(5)
                    content = requests.get(item['url']).content

                media_file.write(content)

            file_time = int(item.get('created_time', item.get('taken_at', time.time())))
            os.utime(file_path, (file_time, file_time))

    @staticmethod
    def get_logger(level=logging.WARNING, log_file='instagram-scraper.log'):
        '''Returns a file logger.'''
        logger = logging.getLogger(__name__)
        logger.setLevel(logging.NOTSET)

        handler = logging.FileHandler(log_file, 'w')
        handler.setLevel(level)

        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        handler.setFormatter(formatter)

        logger.addHandler(handler)
        return logger

    @staticmethod
    def parse_file_usernames(usernames_file):
        '''Parses a file containing a list of usernames.'''
        users = []

        try:
            with open(usernames_file) as user_file:
                for line in user_file.readlines():
                    # Find all usernames delimited by ,; or whitespace
                    users += re.findall(r'[^,;\s]+', line)

                print users
        except IOError as err:
            raise ValueError('File not found ' + err)

        return users

    @staticmethod
    def parse_str_usernames(usernames_str):
        '''Parse the username input as a delimited string of users.'''
        return re.findall(r'[^,;\s]+', usernames_str)


def main():
    parser = argparse.ArgumentParser(
        description="instagram-scraper scrapes and downloads an instagram user's photos and videos.")

    parser.add_argument('username', help='Instagram user(s) to scrape', nargs='*')
    parser.add_argument('--destination', '-d', help='Download destination')
    parser.add_argument('--login_user', '-u', help='Instagram login user')
    parser.add_argument('--login_pass', '-p', help='Instagram login password')
    parser.add_argument('--filename', '-f', help='Path to a file containing a list of users to scrape')

    args = parser.parse_args()

    if (args.login_user and args.login_pass is None) or (args.login_user is None and args.login_pass):
        parser.print_help()
        raise ValueError('Must provide login user AND password')

    if not args.username and args.filename is None:
        parser.print_help()
        raise ValueError('Must provide username(s) OR a file containing a list of username(s)')
    elif args.username and args.filename:
        parser.print_help()
        raise ValueError('Must provide only one of the following: username(s) OR a filename containing username(s)')

    usernames = []

    if args.filename:
        print "expected behavior"
        usernames = InstagramScraper.parse_file_usernames(args.filename)
    else:
        usernames = InstagramScraper.parse_str_usernames(','.join(args.username))

    scraper = InstagramScraper(usernames, args.login_user, args.login_pass, args.destination)
    scraper.scrape()

if __name__ == '__main__':
    main()
