#!/usr/bin/env python

# Process files downloaded by Transmission
# Script should live in /var/lib/transmission/bin

# Environment variables passed by transmission
# TR_APP_VERSION
# TR_TIME_LOCALTIME
# TR_TORRENT_DIR
# TR_TORRENT_HASH
# TR_TORRENT_ID
# TR_TORRENT_NAME

############################
# Settings
############################

# Destincation Directories
MOVIE_DIR = '/var/www/html/media/video'
TV_DIR = '/var/www/html/media/tv'
MUSIC_DIR='/var/www/html/media/music'

# Script Logging
LOG_FILE='/var/lib/transmission/bin/process_download.log'

# Video file extensions
VIDEO_EXTENSIONS = ('.avi','.mp4','.mkv','.asf','.asx','.flv','.mov','.mpg','.rm','.swf','.vob','.wmv')

# Audio file extensions
AUDIO_EXTENSIONS = ('.mp3','.aif','.iff','.m3u','.m4a','.mid','.mpa','.ra','.wav','.wma')

# Whether to preserve all torrents
PRESERVE_TORRENTS = False

# Preserve torrents with this string in path
PRESERVE_TORRENT_STRING = 'iptorrents'

# TODO replace this by looking up the season number online
# Below is for calculating season number for date shows
# Year tv show started
SHOW_YEAR_START = {
	"The Daily Show" : 1996,
	"The Colbert Report" : 2005
}

# Month number that a dated show begins their season
# Normally not exact, but close enough
SHOW_SEASON_START = {
	"The Daily Show" : 10,
	"The Colbert Report" : 10
}

# email settings
EMAIL_FROM = ''
EMAIL_TO = ['']

# Strip from the file paths in the email noitces (to shorten them, more readable)
STRIP_FROM_PATH_IN_EMAIL = ['/var/www/html/media/']

############################
# End Settings
############################


import os
import sys
import re
import shutil
import smtplib
from email.mime.text import MIMEText
import logging

# Keep track of how many files we process
videoFiles = 0
tvFiles = 0
audioFiles = 0
stagedFiles = []

# Just for iptorrents and their names not matching file names
use_torrent_name = False

debug = '--debug' in sys.argv 

# While I'm actively debugging...
debug = True

if debug:
	logging.basicConfig(filename=LOG_FILE,level=logging.DEBUG)
else:
	logging.basicConfig(filename=LOG_FILE,level=logging.INFO)

logging.info("Script started")

# Make sure we're called by transmission
if not os.environ.get('TR_APP_VERSION'):
	logging.error("Not called from Transmission")
	sys.exit(1)

	
def delete_torrent(torrent_id):
	logging.info('Deleting torrent id: ' + torrent_id)
	os.system('transmission-remote -t ' + torrent_id + ' --remove-and-delete')

def is_video(fileName):
	"Check if file extension is in VIDEO_EXTENSIONS"
	return os.path.splitext(fileName)[1] in VIDEO_EXTENSIONS

def is_audio(fileName):
	"Check if file extension is in AUDIO_EXTENSSIONS"
	return os.path.splitext(fileName)[1] in AUDIO_EXTENSIONS

def is_tv(fileName): 
	"Look for pattern in file name indicating an episode number"
	# S00E00
	if re.search('[sS]\d+[eE]\d+',fileName):
		logging.debug("is_tv: matches S00E00")
		return True
	# Sx00
	if re.search('\d+[xX]\d+',fileName):
		logging.debug("is_tv: matches Sx00")
		return True
	# YEAR.MONTH.DAY
	if re.search('\d{4}\.\d{2}\.\d{2}',fileName):
		logging.debug("is_tv: matches YEAR.MONTH.DAY")
		return True
	# iptorrents with S00E00 in torrent name but 000 in file name
	if re.search('[sS]\d+[eE]\d+', os.environ.get('TR_TORRENT_NAME')):
		logging.debug("is_tv: matches IPTORRENTS S00E00 in torrent name")
		use_torrent_name = True
		return True
	return False

def is_video_sample(filePath):
	"Check to see if the video is only a sample -- we don't like samples in our library"
	pDir = os.path.basename(os.path.dirname(filePath))
	fName = os.path.basename(filePath)
	fExt = os.path.splitext(filePath)[1]
	# Easiest is if the directory the file is in is named sample
	if re.search('^sample$', pDir, re.IGNORECASE):
		logging.info('Determined to be sample: ' + fName)
		return True
	# See if file ends with 'sample.ext'
	if re.search('sample' + fExt + '$', fName, re.IGNORECASE):
		logging.info('Determined to be sample: ' + fName)
		return True
	# If all else fails, enable this below: (Anything less than 20MB)
	#if os.getsize(filePath) < 1024 * 1024 * 20
	#	return True
	logging.debug('Determined not to be a sample video: ' + fName)
	return False
	

def clean_tv_name(showName):
	showName = re.sub('\.',' ',showName)
	showName = re.sub('\s$','',showName)
	return showName

def get_tv_parts(fileName):
	global use_torrent_name
	show = dict()
	if use_torrent_name:
		filename = os.environ.get('TR_TORRENT_NAME')
	# Standard S00E00
	if re.search('[sS]\d+[eE]\d+',fileName):
		s = re.search('^(.*)[sS](\d+)[eE]\d+',fileName)
		show['season'] = str(int(s.group(2)))
		show['name'] = clean_tv_name(s.group(1))
		return show
	# Older 0X0
	if re.search('\d+[xX]\d+',fileName):
		s = re.search('^(.*)(\d+)[xX]\d+',fileName)
		show['season'] = str(int(s.group(2)))
		show['name'] = clean_tv_name(s.group(1))
		return show
	# YYYY.MM.DD
	if re.search('\d{4}\.\d{2}\.\d{2}',fileName):
		i = re.search('^(.*)(\d{4})\.(\d{2})\.\d{2}',fileName)
		show['name'] = clean_tv_name(i.group(1))
		year = int(i.group(2))
		month = int(i.group(3))
		# Default to season 0, change if show exists in SHOW_YEAR_START
		season = 0
		if SHOW_YEAR_START[show['name']]:
			season = year - SHOW_YEAR_START[show['name']] + 1
			if month >= SHOW_SEASON_START[show['name']]:
				season += 1
		show['season'] = str(int(season))
		return show
	# Somehow got this far, set default values
	show['name'] = 'Unknown'
	show['season'] = '0'
	return show

def should_preserve_torrent(source):
	if PRESERVE_TORRENTS:
		return True
	if PRESERVE_TORRENT_STRING != '':
		return re.search(PRESERVE_TORRENT_STRING, source)
	logging.info('Will not preserve torrent')
	return False
	
def move_file(source,destDir,destName=''):
	"move or copy (depending on whether to preserve torrent) source to dest directory"
	# source can be a directory
	global stagedFiles
	preserve_torrent = should_preserve_torrent(source)
	if not os.path.exists(destDir):
		logging.debug('Creating directory: ' + destDir)
		os.makedirs(destDir)
	dest = destDir
	if destName != '':
		dest = os.path.join(destDir,destName)
	else:
		dest = os.path.join(destDir, os.path.basename(source))
	# if is rar file, always move b/c we created the file and Transmission will not move or delete it.
	if preserve_torrent and not download['is_rar']:
		shutil.copy(source,dest)
		logging.info('Copied ' + source + ' to ' + dest)
	else:
		shutil.move(source,dest)
		logging.info('Moved ' + source + ' to ' + dest)
	stagedFiles.append(dest)
	
	
	
def process_file (filePath):
	"Check type of file and move to appropriate location"
	global tvFiles, videoFiles, audioFiles
	fileName = os.path.basename(filePath)
	# Should be rare we get an individual audio file, but just in case
	if is_audio(os.path.basename(fileName)):
		logging.debug('File is audio: ' + fileName)
		move_file(filePath,MUSIC_DIR)
		audioFiles += 1
		return
	if is_video(fileName) and not is_video_sample(fileName):
		logging.debug('File is video: ' + fileName)
		if is_tv(fileName):
			logging.debug('File is tv show: ' + filePath)
			showInfo = get_tv_parts(fileName)
			destination = TV_DIR + '/' + showInfo['name'] + '/Season ' + showInfo['season']
			move_file(filePath,destination)
			tvFiles += 1
		else:
			# Don't need to do anything with standard video file except move it over
			logging.debug('File is a movie: ' + filePath)
			move_file(filePath,MOVIE_DIR)
			videoFiles += 1
		return
	# Do nothing if reaching here.  File is probalby junk that was attached to torrent.

def send_email():
	"Sends a summary email to EMAIL_TO"
	logging.info('Sending email')
	body = "Your download of " + os.environ.get('TR_TORRENT_NAME') + ' has completed.\r\n'
	body += '\r\n\r\nFiles processed:\r\n'
	for f in stagedFiles:
		# Shorten the paths down: /var/www/html/media/tv/... becomes tv/...
		for p in STRIP_FROM_PATH_IN_EMAIL:
			f = re.sub(p, '', f)
		body += '  ' + f + '\r\n'
	msg = MIMEText(body)
	msg['From'] = EMAIL_FROM
	msg['To'] = ', '.join(EMAIL_TO)
	msg['Subject'] = "Download complete"

	s = smtplib.SMTP()
	s.server = 'localhost'
	s.connect()
	s.sendmail(EMAIL_FROM, EMAIL_TO, msg.as_string())
	s.close()
	logging.info('email sent')

download = dict()

download['location'] = os.environ.get('TR_TORRENT_DIR') + '/' + os.environ.get('TR_TORRENT_NAME')

download['single_file'] = os.path.isfile(download['location'])
download['multiple_files'] = os.path.isdir(download['location'])

logging.debug("single file = " + str(download['single_file']))
logging.debug("multiple files = " + str(download['multiple_files']))

# Default to not being rar (reset if found to be so)
download['is_rar'] = False

if download['single_file']:
	process_file(download['location'])

if download['multiple_files']:
	# check for rar compressed files first
	for root, dirs, files in os.walk(download['location']):
		for f in files:
			filePath = os.path.join(root,f)
			if os.path.splitext(os.path.basename(filePath))[1] == '.rar':
				logging.info("Calling unrar e for " + filePath)
				curDir = os.path.abspath(os.getcwd())
				os.chdir(download['location'])
				os.system('unrar e -inul -y -o+ "' + filePath + '"') 
				download['is_rar'] = True
				os.chdir(curDir)
	# Check if download is a music album
	a = 0
	for root, dirs, files in os.walk(download['location']):
		for f in files:
			filePath = os.path.join(root,f)
			if is_audio(filePath):
				a += 1
	# Assume that if a > 3 then it's an album -- move the entire directory
	# TODO: This could be done better
	if a > 3:
		logging.info('Moving music album')
		move_file(download['location'], MUSIC_DIR)
	else:
		# Not music, all files uncomressed, process each file individually
		for root, dirs, files in os.walk(download['location']):
			for f in files:
				filePath = os.path.join(root,f)
				if os.path.isfile(filePath):
					logging.info('Processing file ' + filePath)
					process_file(filePath)
	
	
send_email()

if len(stagedFiles) > 0:
	logging.debug("Processed files, checking if torrent should be deleted")
	if not should_preserve_torrent(download['location']):
		logging.info("Torrent should be deleted, calling delete_torrent")
		delete_torrent(os.environ.get('TR_TORRENT_ID'))
	else:
		logging.info("Torrent will not be deleted")
else:
	logging.warn("Unable to process any files in download")

logging.info("Script finished")
sys.exit(0)
