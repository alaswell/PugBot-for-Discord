# MongoDB.py for use with PugBot-for-Discord
# Function: Create a new mongo database to save last and server information
# Create by: Alex Laswell 

# imports 
import pymongo
import time
# pprint library is used to make the output look more pretty
from pprint import pprint

# connect to the MongoDB, change the << MONGODB URL >> to reflect your own connection string
client = pymongo.MongoClient(<<MONGODB URL>>)

# create a new Mongo database called Game
db=client.Game

# get the current time for a start
time = time.time()

# Mongo uses documents (key:value pairs) to represent rows of data
pickup = {	'blueteam': ['player0','player1','player2','player3'],
			'last':True,
			'map': 'A New Begining',
			'redteam': ['player4','player5','player6','player7'],
			'time': time }

# pickups is the collection (read: table) and pickup is the document (read: row)		
id = db.pickups.insert_one(pickup)

# verify we have done this correctly
last = db.pickups.find_one({})

print('Newly Entered Document:')
pprint(last)