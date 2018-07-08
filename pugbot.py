# Pickup Game Bot for use with discord
# Modified by: Alex Laswell for use with Fortress Forever
# Based on: 
#	PugBot-for-Discord by techlover1 https://github.com/techlover1/PugBot-for-Discord
			
# Imports
from collections import OrderedDict
from datetime import timedelta
from pymongo.collection import ReturnDocument
from random import shuffle
from random import choice
import asyncio
import config
import discord
import pymongo
import requests
import time
import valve.rcon

# All of these are set in the config file
adminRoleID = config.adminRoleID
adminRoleMention = config.adminRoleMention
blueteamChannelID = config.blueteamChannelID
cmdprefix = config.cmdprefix
discordServerID = config.discordServerID
dbtoken = config.dbtoken
durationOfCheckin = config.durationOfCheckin
durationOfMapVote = config.durationOfMapVote
durationOfReadyUp = config.durationOfReadyUp
durationOfVeto = config.durationOfVeto
playerRoleID = config.playerRoleID
poolRoleID = config.poolRoleID
quotes = config.quotes
readyupChannelID = config.readyupChannelID
redteamChannelID = config.redteamChannelID
requestChannelID = config.requestChannelID
rconPW = config.rconPW
serverID = config.serverID
serverPW = config.serverPW
server_address  = config.server_address
singleChannelID = config.singleChannelID
sizeOfTeams = config.sizeOfTeams
sizeOfGame = config.sizeOfGame
sizeOfMapPool = config.sizeOfMapPool
timeoutRoleID = config.timeoutRoleID
token = config.token 

# Begin by creating the client and server object
client = discord.Client()
server = client.get_server(id=discordServerID)

# create the MongoDB client and connect to the database
dbclient = pymongo.MongoClient(dbtoken)
db = dbclient.FortressForever

# Globals 
chosenMap = []
lastMap = []
mapPicks = {}
lastRedTeam = []
lastBlueTeam = []
lasttime = time.time()
players = []
starter = []
starttime = time.time()
mapMode = True
pickupRunning = False
randomTeams = False	
selectionMode = False
voteForMaps = True
		
# Constants 
FIVE_SECONDS = 5

# Setup an RCON connection 
rcon = valve.rcon.RCON(server_address, rconPW)
rcon.connect()
rcon.authenticate()
	
# run through the all the players in the pool and verify they are ready
async def check_for_afk_players(msg, players, readyupChannelID):
	ready_channel = discord.utils.get(msg.server.channels, id = readyupChannelID)
	ready_users = ready_channel.voice_members
	afk_players = []
	
	# only preform this check if the readyupChannelID is a valid voice channel
	if(ready_channel is not None):
		# check to verify if each player is in the ready-up channel
		for p in players:
			if(p not in ready_users):				
				afk_players.append(p)	# add to missing players list
	return afk_players
	
# check that the admin who started the game is still here
async def check_for_afk_admin(msg, game_starter):
	# check for advanced filtering
	def check(msg):
		return msg.content.startswith(cmdprefix + 'here')
	inputobj = await client.wait_for_message(timeout=durationOfCheckin, author=game_starter, check=check)
	# wait_for_message returns 'None' if asyncio.TimeoutError thrown
	if(inputobj != None): # game_starter did !checkin
		return True
	else: # game_starter did not !checkin
		return False
		
async def check_for_map_nominations(mapPicks, msg, sizeOfGame, sizeOfMapPool, pickupRunning, players):
	while(len(mapPicks) < sizeOfMapPool and pickupRunning and len(players) == sizeOfGame):
		# need to build the list of maps
		mapStr = ""
		for k in mapPicks:
			mapStr = mapStr + str(mapPicks[k]) + " (" + k.mention + ")\n"
		await send_emb_message_to_channel(0xff0000, "Players must nominate more maps before we can proceed\nCurrently Nominated Maps (" + str(len(mapPicks)) + "/" + str(sizeOfMapPool) + ")\n" + mapStr, msg)
		async def needMapPicks(msg):						
			# check function for advanced filtering
			def check(msg):
				return msg.content.startswith(cmdprefix + 'nominate')
			# wait until someone nominates another map
			await client.wait_for_message(timeout=30, check=check)
		await needMapPicks(msg)

async def check_for_veto(command, msg, game_starter):
	# generic check to allow game_starter to !veto another admin's command
	await send_emb_message_to_channel(0xff0000, game_starter.mention + "\n\n" + msg.author.mention + " is trying to " + command + " your pickup. You have " + str(durationOfVeto) + " seconds to " + cmdprefix + "veto them, or the command will happen", msg)
	# check for advanced filtering
	def check(msg):
		return msg.content.startswith(cmdprefix + 'veto')
	inputobj = await client.wait_for_message(timeout=durationOfVeto, author=game_starter, check=check)
	# wait_for_message returns 'None' if asyncio.TimeoutError thrown
	if(inputobj != None): # game_starter did !veto the command		
		return True
	else: # game_starter did not !veto
		return False
		
async def count_votes_message_channel(tdelta, keys, msg, votelist, votetotals):
	values = []
	totals = {}
	tmpstr = ''
	# reset totals
	votetotals = []
	[votetotals.append(0) for x in range(sizeOfMapPool)]
	# tally the buckets
	for k,v in votelist.items():
		votetotals[v-1] += 1
	# zip with keys to make a nice dict
	totals = OrderedDict(zip(keys, votetotals))
	for x,y in totals.items():
		tmpstr = tmpstr + str(x) + " : " + str(y) + "\n"
	# set up the remaining time to vote timedelta
	tdelta0 = tdelta - timedelta(microseconds=tdelta.microseconds)
	await send_emb_message_to_channel(0x00ff00, tmpstr + "\n" + str(durationOfMapVote - tdelta0.total_seconds()) + " seconds remaining", msg)
		
async def go_go_gadget_pickup(mapMode, mapPicks, msg, selectionMode, starter, pickupRunning, players, poolRoleID, readyupChannelID, voteForMaps):
	afk_players = []
	counter = 0
	pick_captains_counter = 0
	countdown = time.time()
	elapsedtime = time.time() - countdown
	td = timedelta(seconds=elapsedtime)
	ready_channel = discord.utils.get(msg.server.channels, id = readyupChannelID)
	role = discord.utils.get(msg.server.roles, id=poolRoleID)
	
	await send_emb_message_to_channel(0x00ff00, "The pickup is starting!!\n\n" + role.mention + " join the " + ready_channel.name + " to signify you are present and ready", msg)
	
	# set up the embeded message incase we need to message players 
	emb = (discord.Embed(title="The pickup is starting!!\n\nJoin the " + ready_channel.name + " to signify you are present and ready", colour=0xff0000))
	emb.set_author(name=client.user.name, icon_url=client.user.avatar_url)
	# give the players time to ready-up
	while(td.total_seconds() < durationOfReadyUp):
		# only check every 5 seconds
		await asyncio.sleep(5)
		# loop through the channel and check to see if everyone has joined it or not
		afk_players = await check_for_afk_players(msg, players, readyupChannelID)
		if(len(afk_players) > 0):
			afkstr = '\n'.join([p.mention for p in afk_players])			
			elapsedtime = time.time() - countdown
			td = timedelta(seconds=elapsedtime)
			# only message everyone on every third iteration
			if((counter % 3) == 0):
				await send_emb_message_to_channel(0xff0000, "Missing players:\n\n" + afkstr, msg)
				for p in afk_players:
					try:
						await client.send_message(p, embed=emb )	
					except Exception:
						pass
			counter += 1
		else:
			# all players in list are idle in channel and ready
			break
	
	# if afk_players has people in it, then those player(s) timed out
	if(len(afk_players) > 0):		
		for idleUser in afk_players:		
			players.remove(idleUser)		# remove from players list
			mapPicks.pop(idleUser, None)	# remove this players nomination if they had one
			try:
				await client.remove_roles(idleUser, role)
			except Exception:
				pass
			await send_emb_message_to_channel(0xff0000, idleUser.mention + " has been removed from the pickup due to inactivity", msg)
			await client.change_presence(game=discord.Game(name='Pickup (' + str(len(players)) + '/' + str(sizeOfGame) + ') ' + cmdprefix + 'add'))
		return	False # break out if we remove a player
	
	inputobj = 0			# used to manipulate the objects from messages
	mapMode = True			# allow nominations until we have a full maplist
	randomTeams = True		# if game starter does not change, will pick teams randomly from players list
	selectionMode = True	# keep people from changing the queue once the game has begun
	shuffle(players) 		# shuffle the player pool
	
	# lists for team selection
	caps = []
	redTeam = []
	blueTeam = []
	playerPool = []
	
	await send_emb_message_to_channel(0x00ff00, "All players are confirmed ready!", msg)

	# Verifying admin status if they have not already confirmed ready
	if starter[0] not in players:
		await send_emb_message_to_channel(0xffa500, "Verifying that we have an admin\n\n" + starter[0].mention + " please reply with !here so we can proceed", msg)
		adminPresent = False
		while not adminPresent:
			adminPresent = await check_for_afk_admin(msg, starter[0])
			if not adminPresent:
				# do we have an admin in the pool we can give the pickup to
				for p in players:
					if(await user_has_access(p)):
						# admin found : transfering pickup
						await send_emb_message_to_channel(0xff0000, starter[0].mention + " seems to be missing\n\nTransfering the game to " + p.mention, msg)
						starter[0] = p
						adminPresent = True
						break # no need to find another admin
				if not adminPresent:
					# try to private message the game_starter
					emb = (discord.Embed(description="You did not reply with !here and your pickup has been put on hold", colour=0xff0000))
					emb.set_author(name=client.user.name, icon_url=client.user.avatar_url)
					await client.send_message(starter[0], embed=emb )
					# ping all admins to see if someone can take over
					role = discord.utils.get(msg.server.roles, id=adminRoleID)
					await send_emb_message_to_channel(0xff0000, role.mention + " the admin who started this pickup seems to be missing. !transfer and save the pickup", msg)
	# adminPresent == True
	
# Begin the pickup
	
	# Map Selection
	await client.change_presence(game=discord.Game(name='Map Selection'))
	
	# do we have the right amount of map nominations
	await check_for_map_nominations(mapPicks, msg, sizeOfGame, sizeOfMapPool, pickupRunning, players)
	
	# are we still full
	if(len(players) < sizeOfGame):
		# not full
		await send_emb_message_to_channel(0xff0000, "ABORTING: The pickup is no longer full", msg)
		await client.change_presence(game=discord.Game(name='Pickup (' + str(len(players)) + '/' + str(sizeOfGame) + ') ' + cmdprefix + 'add'))
		return False 
		
	# vote for maps
	chosenMap = await  pick_map(lastMap, mapMode, msg, players, poolRoleID, sizeOfGame, sizeOfMapPool, voteForMaps)
	
	# make sure we are still full
	if(len(players) < sizeOfGame):
		# not full
		await send_emb_message_to_channel(0xff0000, "ABORTING: The pickup is no longer full", msg)
		await client.change_presence(game=discord.Game(name='Pickup (' + str(len(players)) + '/' + str(sizeOfGame) + ') ' + cmdprefix + 'add'))
		return False 
	
	# by having the game admin approve 
	# we can make sure teams end up fair more often
	adminApproves = False
	while not adminApproves:
		# loop until the game starter makes a decision
		pick_captains_counter = 1	# tracks how many times the game_starter has been asked
		randomTeams = await pick_captains(msg, caps, players, blueTeam, redTeam)
		while(len(caps) < 2):
			if(len(players) < sizeOfGame):
				if(len(players) > 0):
					# game is no longer full
					await send_emb_message_to_channel(0xff0000, "ABORTING: The pickup is no longer full", msg)
					await client.change_presence(game=discord.Game(name='Pickup (' + str(len(players)) + '/' + str(sizeOfGame) + ') ' + cmdprefix + 'add'))
					return False 
				else:
					# game has been !ended 
					await client.change_presence(game=discord.Game(name=' '))
					return True
			elif(pick_captains_counter > 2):
				# game_starter is afk ... pug will be ended
				role = discord.utils.get(msg.server.roles, id=poolRoleID)
				await send_emb_message_to_channel(0xff0000, "This pickup has been abandoned by the admin and will now be ended\n\n" + role.mention + " someone who is here, will need to start a new one", msg)
				await client.change_presence(game=discord.Game(name=' '))
				return True
			else:
				randomTeams = await pick_captains(msg, caps, players, blueTeam, redTeam)
				pick_captains_counter += 1
			
		# one last time ... make sure we are still full
		if(len(players) < sizeOfGame):
			# not full
			await send_emb_message_to_channel(0xff0000, "ABORTING: The pickup is no longer full", msg)
			await client.change_presence(game=discord.Game(name='Pickup (' + str(len(players)) + '/' + str(sizeOfGame) + ') ' + cmdprefix + 'add'))
			return False 
			
		# set up the initial teams
		if(randomTeams):
			for i in range(0, sizeOfTeams):
				redTeam.append(players[i])
				blueTeam.append(players[i+sizeOfTeams])
		else:
			blueTeam = [caps[0]]
			redTeam = [caps[1]]
			
			# copy the player pool over
			for p in players:
				if p not in caps:
					playerPool.append(p)
						
		# Switch off picking until the teams are all full
		await client.change_presence(game=discord.Game(name='Team Selection'))
		
		# if teams are not already full:
		if(len(redTeam) < sizeOfTeams and len(blueTeam) < sizeOfTeams):
			if(len(players) < sizeOfGame):
				# someone has left the pug
				await send_emb_message_to_channel(0xff0000, "ABORTING: The pickup is no longer full", msg)
				await client.change_presence(game=discord.Game(name='Pickup (' + str(len(players)) + '/' + str(sizeOfGame) + ') ' + cmdprefix + 'add'))
				return False 

			await send_emb_message_to_channel(0x00ff00, caps[0].mention + " vs " + caps[1].mention, msg)
			# Blue captain picks first
			await blue_team_picks(blueTeam, redTeam, caps, playerPool, msg)
			if(len(playerPool) > 1):
				# only make the captain pick if they have a choice
				await red_team_picks(blueTeam, redTeam, caps, playerPool, msg)
			else:
				redTeam.append(playerPool[0])
				await send_emb_message_to_channel_red(playerPool[0].mention + " has been added to the team", msg)
			while(len(redTeam) < sizeOfTeams and len(blueTeam) < sizeOfTeams):
				if(len(players) < sizeOfGame):
					# someone has left the pug
					await send_emb_message_to_channel(0xff0000, "ABORTING: The pickup is no longer full", msg)
					await client.change_presence(game=discord.Game(name='Pickup (' + str(len(players)) + '/' + str(sizeOfGame) + ') ' + cmdprefix + 'add'))
					return False 

				# Red captain gets two picks first round so start with red
				await red_team_picks(blueTeam, redTeam, caps, playerPool, msg)
				
				if(len(playerPool) > 1):
					# only make the captain pick if they have a choice
					await blue_team_picks(blueTeam, redTeam, caps, playerPool, msg)
				else:
					blueTeam.append(playerPool[0])
					await send_emb_message_to_channel_blue(playerPool[0].mention + " has been added to the team", msg)
		# both teams are full
		# verify everything looks good		
		await send_emb_message_to_channel_blue('\n'.join([p.mention for p in blueTeam]), msg)	# Blue Team information				
		await send_emb_message_to_channel_red('\n'.join([p.mention for p in redTeam]), msg)		# Red Team information	
		await send_emb_message_to_channel(0xffa500, starter[0].mention + " these are the teams\n\nReply with !accept to accept them or with !repick and we can choose again", msg)
		didChoose = False
		while not didChoose:
			# check for advanced filtering
			def check(msg):
				if(msg.content.startswith(cmdprefix + 'accept') or msg.content.startswith(cmdprefix + 'repick')): return True
				return False
			inputobj = await client.wait_for_message(timeout=durationOfCheckin, author=starter[0], check=check)
			# wait_for_message returns 'None' if asyncio.TimeoutError thrown
			if(inputobj != None): 
				didChoose = True
				# switch on choice
				if(inputobj.content.startswith(cmdprefix + "accept")):
					adminApproves = True
				elif(inputobj.content.startswith(cmdprefix + "repick")):
					# reset so we can pick new teams
					caps = []
					redTeam = []
					blueTeam = []
					playerPool = []
					adminApproves = False
			else: 
				didChoose = False
				await send_emb_message_to_channel(0xff0000, starter[0].mention + " please make a selection:\n\n!accept to **accept** the teams\n\n!repick to discard these teams and **repick** new ones", msg)
	# adminApproves and everything is set
	
	# pm users and message server with game information
	await send_information(blueTeam, redTeam, chosenMap, msg, serverID, serverPW)
	
	# change the map in the server to the chosen map
	try:
		rcon.execute('changelevel ' + chosenMap)
	except Exception:
		pass
	
	# move the players to their respective voice channels
	for p in redTeam:
		try:
			await client.move_member(p, client.get_channel(redteamChannelID))
		except(InvalidArgument, HTTPException, Forbidden):
			continue				
	for p in blueTeam:
		try:
			await client.move_member(p, client.get_channel(blueteamChannelID))
		except(InvalidArgument, HTTPException, Forbidden):
			continue
	
	# Save all the information for !last
	await save_last_game_info(blueTeam, redTeam, lastBlueTeam, lastRedTeam, chosenMap)
	
	# schedule a background task to remove the players from the pool
	# this is so we can still notify them all for a few minutes
	client.loop.create_task(remove_everyone_from_pool_role(msg, redTeam, blueTeam, poolRoleID))
		
	return True

# Lists all of the maps in the MongoDB table : maps
async def list_all_the_maps(msg):
	# create the MongoDB client and connect to the database
	dbclient = pymongo.MongoClient(dbtoken)
	# find will return all documents in the maps collection		
	foundmaps = dbclient.FortressForever.maps.find( { } )	
	# convert to a list so we can index into it
	maps = list(foundmaps)
	
	# with the aliases, this message gets big quickly so we    
	# need to chunk up the maplist into sections to accomidate 
	
					## Part I   ##
	emb = (discord.Embed(description = "Currently, you may nominate any of the following maps:", colour=0xffa500))
	emb.set_author(name=client.user.name, icon_url=client.user.avatar_url)	
	for map in maps[:20]:
		emb.add_field(name=str(map['name']), value=str(map['aliases']), inline=False)
	await client.send_message(msg.author, embed=emb )
					## Part II  ##
	emb = (discord.Embed(description = "", colour=0xffa500))
	emb.set_author(name=client.user.name, icon_url=client.user.avatar_url)
	for map in maps[20:40]:
		emb.add_field(name=str(map['name']), value=str(map['aliases']), inline=False)
	await client.send_message(msg.author, embed=emb )
					## Part III ##
	emb = (discord.Embed(description = "", colour=0xffa500))
	emb.set_author(name=client.user.name, icon_url=client.user.avatar_url)
	for map in maps[40:60]:
		emb.add_field(name=str(map['name']), value=str(map['aliases']), inline=False)
	await client.send_message(msg.author, embed=emb )
					## Part IV  ##
	emb = (discord.Embed(description = "", colour=0xffa500))
	emb.set_author(name=client.user.name, icon_url=client.user.avatar_url)
	for map in maps[60:80]:
		emb.add_field(name=str(map['name']), value=str(map['aliases']), inline=False)
	await client.send_message(msg.author, embed=emb )
					## Part V  ##
	emb = (discord.Embed(description = "", colour=0xffa500))
	emb.set_author(name=client.user.name, icon_url=client.user.avatar_url)
	for map in maps[80:100]:
		emb.add_field(name=str(map['name']), value=str(map['aliases']), inline=False)
	await client.send_message(msg.author, embed=emb )
					## Part VI ##
	emb = (discord.Embed(description = "", colour=0xffa500))
	emb.set_author(name=client.user.name, icon_url=client.user.avatar_url)
	for map in maps[100:]:
		emb.add_field(name=str(map['name']), value=str(map['aliases']), inline=False)
	await client.send_message(msg.author, embed=emb )
	
# Check to see if the map nominated is an alias
async def mapname_is_valid(msg, mpname):
	# create the MongoDB client and connect to the database
	dbclient = pymongo.MongoClient(dbtoken)
	
	# check in name
	cursor = dbclient.FortressForever.maps.find( { "$or":[{'name': mpname}, {'name': "ff_" + mpname}, {"aliases":mpname}] } )
	for map in cursor:
		return map['name']
	return "INVALID"
		
# wait until the game starter makes a decision				
async def pick_captains(msg, caps, players, blueTeam, redTeam):
	game_starter = msg.server.get_member(starter[0].id)
	bcap = client.user.name
	rcap = client.user.name
	# set presence 
	await client.change_presence(game=discord.Game(name='Selecting Captains'))
	
	# human readable Usage message to channel
	emb = (discord.Embed(description=game_starter.mention + " please select one of the options below", colour=0xffa500))
	emb.set_author(name=client.user.name, icon_url=client.user.avatar_url)
	emb.add_field(name=cmdprefix + 'captains', value='to manually select the captains', inline=False)
	emb.add_field(name=cmdprefix + 'manual', value='to manually select both teams', inline=False)
	emb.add_field(name=cmdprefix + 'shuffle', value='to randomize the captains', inline=False)
	emb.add_field(name=cmdprefix + 'random', value='to randomize the teams', inline=False)
	await client.send_message(msg.channel, embed=emb )
	
	# check function for advance filtering
	def check(msg):
		if( msg.content.startswith(cmdprefix + 'captains')): return True
		elif( msg.content.startswith(cmdprefix + 'manual')): return True
		elif( msg.content.startswith(cmdprefix + 'shuffle')): return True
		elif( msg.content.startswith(cmdprefix + 'random')): return True
		return False
		
	# wait up to two (2) minutes for the game starter to make a decision
	inputobj = await client.wait_for_message(timeout=120, author=game_starter, check=check)
	
	# wait_for_message returns 'None' if asyncio.TimeoutError thrown
	if(inputobj != None): 
		# switch on choice
		if(inputobj.content.startswith(cmdprefix + "captains")):
			# msg.mentions returns an unordered list 
			# therfor we have to get each name individually 
			# this way the admin has control over who is blue and red
			plyrStr = '\n'.join([p.mention for p in players])
			await send_emb_message_to_channel_blue(game_starter.mention + " pick the blue team captain using @playername in your reply. Available players are:\n\n" + plyrStr, msg)
			# await send_emb_message_to_channel(0x00ff00, game_starter.mention + " pick the blue team captain using @playername in your reply", msg)
			while bcap == client.user.name:
				try:
					# try to get the user the admin has specified
					inputobj = await client.wait_for_message(timeout=60, author=game_starter)
					if(inputobj != None):
						bcap = inputobj.mentions[0]
						if(bcap not in players):
							await send_emb_message_to_channel(0xff0000, game_starter.mention + " player must be added to the pickup. Available players are:\n\n" + plyrStr, msg)
							bcap = client.user.name
					else: # timeout
						await send_emb_message_to_channel_blue(game_starter.mention + " pick the blue team captain using @playername in your reply. Available players are:\n\n" + plyrStr, msg)
				except(IndexError):
					# keep trying if they did not mention someone
					await send_emb_message_to_channel_blue(game_starter.mention + " pick the blue team captain using @playername in your reply. Available players are:\n\n" + plyrStr, msg)
			# do the same for red team
			temp = []	# list for players
			for p in players:
				if p != bcap:
					temp.append(p)
			plyrStr = '\n'.join([p.mention for p in temp])
			await send_emb_message_to_channel_red(game_starter.mention + " pick the red team captain using @playername in your reply. Available players are:\n\n" + plyrStr, msg)
			while rcap == client.user.name:
				try:
					# try to get the user the admin has specified
					inputobj = await client.wait_for_message(timeout=60, author=game_starter)
					if(inputobj != None):
						rcap = inputobj.mentions[0]
						if(rcap not in players):
							await send_emb_message_to_channel(0xff0000, game_starter.mention + " player must be added to the pickup. Available players are:\n\n" + plyrStr, msg)
							rcap = client.user.name
					else: # timeout
						await send_emb_message_to_channel_red(game_starter.mention + " pick the red team captain using @playername in your reply. Available players are:\n\n" + plyrStr, msg)
				except(IndexError):
					# keep trying if they did not mention someone
					await send_emb_message_to_channel_red(game_starter.mention + " pick the red team captain using @playername in your reply. Available players are:\n\n" + plyrStr, msg)
			if(bcap == rcap):
				await send_emb_message_to_channel(0xff0000, game_starter.mention + " you cannot pick the same captain for both teams", msg)
				return False	
			else:
				caps.append(bcap)
				caps.append(rcap)
				return False
		if(inputobj.content.startswith(cmdprefix + "manual")):
			plyrStr = ""
			# do the picking here so that teams are full before we leave this function
			while len(blueTeam) != sizeOfTeams:
				plyrStr = ""
				for p in players:
					if p not in blueTeam:
						plyrStr += p.mention
						plyrStr += "\n"
				await send_emb_message_to_channel_blue(game_starter.mention + " pick the players for the blue team using !blue <@playername>, <@playername>, ... , <@playername> in your reply.\n\nAvailable players are:\n\n" + plyrStr + "\n\n**Current players** are: " + '\n'.join([p.mention for p in blueTeam]), msg)
				# check function for advance filtering
				def check(msg):
					return msg.content.startswith(cmdprefix + 'blue ')					
				# try to get the users the admin has specified
				inputobj = await client.wait_for_message(timeout=60, author=game_starter, check=check)
				if(inputobj != None):
					for p in inputobj.mentions:
						if(p not in players):
							await send_emb_message_to_channel(0xff0000, p.mention + " is not added to the pickup." + game_starter.mention + " you will need to pick someone else", msg)
						else:
							blueTeam.append(p)
					if len(blueTeam) < sizeOfTeams:
						# not enough players in blueTeam 
						await send_emb_message_to_channel(0xff0000, game_starter.mention + " this team is not full, you will need to pick " + (sizeOfTeams - len(blueTeam)) + " more players", msg)
					elif len(blueTeam) > sizeOfTeams:
						# too many players in blueTeam
						# loop until we have the right number
						while len(blueTeam) != sizeOfTeams:
							if len(blueTeam) < sizeOfTeams:
								# admin took too many players off
								# break and let outter loop handle this case
								break
							await send_emb_message_to_channel(0xff0000, game_starter.mention + " this team has too many players. Pick player(s) to take off using !takeoff <@playername>, <@playername>, ... , <@playername>\n\nCurrent players are:\n\n" + '\n'.join([p.mention for p in blueTeam]), msg)
							# loop until the admin has specified someone
							didRemove = False
							while not didRemove:
								# check for advanced filtering
								def check(msg):
									return msg.content.startswith(cmdprefix + 'takeoff')
								inputobj = await client.wait_for_message(timeout=60, author=game_starter, check=check)
								if(inputobj != None):
									for p in inputobj.mentions:
										xtra = p
										if(xtra not in blueTeam):
											await send_emb_message_to_channel(0xff0000, game_starter.mention + " that player is not on the team you will need to pick someone else", msg)
										else:
											# remove this player
											blueTeam.remove(xtra)
											didRemove = True
								else: # timeout
									await send_emb_message_to_channel(0xff0000, game_starter.mention + " pick the extra player to take off using !takeoff @playername in your reply. Current players are:\n\n" + '\n'.join([p.mention for p in blueTeam]), msg)						
				else: # timeout means the admin never replied correctly -> check()
					await send_emb_message_to_channel_blue(adminRoleMention + " please !transfer if the game starter is missing", msg)
			# blueTeam is full
			# everyone else goes into the redTeam
			for p in players:
				if p not in blueTeam:
					redTeam.append(p)
			if len(redTeam) < sizeOfTeams:
				# this should never happen, but just in case
				await send_emb_message_to_channel(0xff0000, "The teams are not even " + game_starter.mention + " we need to do this again", msg)
				return False
			else:
				# Success, so we need to setup captains to break out of outter loop 
				caps.append(blueTeam[0])
				caps.append(redTeam[0])
				return False
		elif(inputobj.content.startswith(cmdprefix + "shuffle")):
			if(len(players) >= 2):
				caps.append(players[0])
				caps.append(players[1])
			else:
				# not enough players 
				caps.append(game_starter)
				caps.append(game_starter)
			return False
		elif(inputobj.content.startswith(cmdprefix + "random")):
			if(len(players) >= 2):
				caps.append(players[0])
				caps.append(players[1])
			else:
				# not enough players
				caps.append(game_starter)
				caps.append(game_starter)
			return True
		else:
			return False	# not a valid option
	else: #inputobj == None
		return False	# timeout

async def pick_map(lastMap, mapMode, msg, players, poolRoleID, sizeOfGame, sizeOfMapPool, voteForMaps):
# vote for maps or random
	if(voteForMaps):
		votelist = {}
		keys = []
		for k,v in mapPicks.items():
			keys.append(v)
		votetotals = []
		[votetotals.append(0) for x in range(sizeOfMapPool)]
		positions = []
		countdown = time.time()
		elapsedtime = time.time() - countdown
		td = timedelta(seconds=elapsedtime)
		counter = 0
		position = 0
		topvote = -1
		duplicateFnd = False
		role = discord.utils.get(msg.server.roles, id=poolRoleID)
		await send_emb_message_to_channel(0x00ff00, "Map voting has started\n\n" + role.mention + " you have " + str(durationOfMapVote) + " seconds to vote for a map\n\nreply with a number between 1 and " + str(sizeOfMapPool) + " to cast your vote", msg)
		await count_votes_message_channel(td, keys, msg, votelist, votetotals)
		while(td.total_seconds() < durationOfMapVote and len(players) == sizeOfGame):
			async def gatherVotes(msg):						
				# check function for advance filtering
				def check(msg):
					# only accept votes from members in the pool
					# update the vote if they change it
					if(poolRoleID in [r.id for r in msg.author.roles]):
						for x in range(1,sizeOfMapPool+1):
							if(msg.content == str(x)):
								votelist.update({msg.author.name:x})
						return True
				# listen for votes, wait no more than 5 seconds between messages
				# this forces the counter to increment more often (read: more messages to the channel)
				await client.wait_for_message(timeout=FIVE_SECONDS, check=check)
			await gatherVotes(msg)
			elapsedtime = time.time() - countdown
			td = timedelta(seconds=elapsedtime)
			# message everyone the maps votes on every even iteration
			if((counter % 2) == 1 and (td.total_seconds() < durationOfMapVote)):
				await count_votes_message_channel(td, keys, msg, votelist, votetotals)
			counter += 1
			
			
		# vote time has expired
		await send_emb_message_to_channel(0xff0000, "Map voting has finished", msg)
		
		# if users have voted
		if(len(votetotals) > 0):
			# tally up the votes
			for k,v in votelist.items():
				votetotals[v-1] += 1 
				
			# find the max number and it's position
			for pos, vote in enumerate(votetotals):
				if(topvote < vote): 
					topvote = vote
					position = pos
					
			# now that we have the max and it's position
			# loop one final time to gather positions of duplicates
			for pos, vote in enumerate(votetotals):
				if(topvote != vote): continue # keep looping if they are different
				# topvote == vote therefor we have a tie
				if(not duplicateFnd): duplicateFnd = True
				positions.append(pos)
		else:
			duplicateFnd = True
			positions = list(range(1, sizeOfMapPool))
			
		# randomly pick from list if we have a tie
		if(duplicateFnd):		
			position = choice(positions)
		mappa = list(mapPicks.values())[position]	
	else: # random map mode
		selector, mappa = choice(list(mapPicks.items()))				
	# tell the users what map won
	emb = (discord.Embed(title="The map has been selected", colour=0x00ff00))
	emb.set_author(name=client.user.name, icon_url=client.user.avatar_url)
	emb.add_field(name='Map', value=str(mappa))										# Display the map information
	await client.send_message(msg.channel, embed=emb )
	
	# reset for next pickup
	lastMap = mappa
	mapMode = False
	return mappa
	
# BLUE TEAM PICKS
async def blue_team_picks(blueTeam, redTeam, caps, players, msg):
	plyrStr = '\n'.join([p.mention for p in players])
	await send_emb_message_to_channel(0x00ff00, caps[0].mention + " type @player to pick. Available players are:\n\n" + plyrStr, msg)

	# check for a pick and catch it if they don't mention an available player
	while True:
		try:
			inputobj = await client.wait_for_message(author=msg.server.get_member(caps[0].id))
			picked = inputobj.mentions[0]
		except(IndexError):
			continue
		break

	# If the player is in players and they are not already picked, add to the team
	if(picked in players):
		if(picked not in redTeam and picked not in blueTeam):
			blueTeam.append(picked)
			players.remove(picked)
			await send_emb_message_to_channel_blue(picked.mention + " has been added to the team", msg)
		else:
			await send_emb_message_to_channel(0xff0000, picked.mention + " is already on a team", msg)
			await blue_team_picks(blueTeam, redTeam, caps, players, msg)
	else:
		await send_emb_message_to_channel(0xff0000, picked.mention + " is not in this pickup", msg)
		await blue_team_picks(blueTeam, redTeam, caps, players, msg)
		
# RED TEAM PICKS
async def red_team_picks(blueTeam, redTeam, caps, players, msg):
	plyrStr = '\n'.join([p.mention for p in players])
	await send_emb_message_to_channel(0x00ff00, caps[1].mention + " type @player to pick. Available players are:\n\n" + plyrStr, msg)

	# check for a pick and catch it if they don't mention an available player
	while True:
		try:
			inputobj = await client.wait_for_message(author=msg.server.get_member(caps[1].id))
			picked = inputobj.mentions[0]
		except(IndexError):
			continue
		break

	# If the player is in players and they are not already picked, add to the team
	if(picked in players):
		if(picked not in redTeam and picked not in blueTeam):
			redTeam.append(picked)
			players.remove(picked)
			await send_emb_message_to_channel_red(picked.mention + " has been added to the team", msg)
		else:
			await send_emb_message_to_channel(0xff0000, picked.mention + " is already on a team", msg)
			await red_team_picks(blueTeam, redTeam, caps, players, msg)
	else:
		await send_emb_message_to_channel(0xff0000, picked.mention + " is not in this pickup", msg)
		await red_team_picks(blueTeam, redTeam, caps, players, msg)

# remove the poolRoleID from all the players from the last pickup	
async def remove_everyone_from_pool_role(msg, redTeam, blueTeam, poolRoleID):
	# wait five minutes 
	await asyncio.sleep(300)
	# get the correct role
	role = discord.utils.get(msg.server.roles, id=poolRoleID)
	# remove from all users in both teams
	for p in redTeam:
		await client.remove_roles(p, role)
	for p in blueTeam:
		await client.remove_roles(p, role)
	# reset presence to nothing
	await client.change_presence(game=discord.Game(name=''))
		
async def save_last_game_info(blueTeam, redTeam, lastBlueTeam, lastRedTeam, lastmap):
	lastRedTeam = []
	lastBlueTeam = []
	for p in redTeam:
		lastRedTeam.append(p.name)
	for p in blueTeam:
		lastBlueTeam.append(p.name)
	lasttime = time.time()
	
	# create the MongoDB client and connect to the database
	dbclient = pymongo.MongoClient(dbtoken)
	db = dbclient.FortressForever
	
	# modify the MongoDB document to contain the most recent pickup information
	updated = db.pickups.update_one({'last':True}, 
									{'$set': {'blueteam':lastBlueTeam,
									'redteam':lastRedTeam, 
									'map':lastmap, 
									'time':lasttime}})
		
# Send a rich embeded messages instead of a plain ones
# to an entire channel
async def send_emb_message_to_channel(colour, embstr, message):
	emb = (discord.Embed(description=embstr, colour=colour))
	emb.set_author(name=client.user.name, icon_url=client.user.avatar_url)
	await client.send_message(message.channel, embed=emb )

# Send a rich embeded messages instead of a plain ones
# to an entire channel - Blue Team Logo
async def send_emb_message_to_channel_blue(embstr, message):
	emb = (discord.Embed(description=embstr, colour=0x0000ff))
	emb.set_author(name='Blue Team', icon_url='http://www.lexicondesigns.com/images/other/ff_logo_blue.png')
	await client.send_message(message.channel, embed=emb )
	
# Send a rich embeded messages instead of a plain ones
# to an entire channel - Red Team Logo
async def send_emb_message_to_channel_red(embstr, message):
	emb = (discord.Embed(description=embstr, colour=0xff0000))
	emb.set_author(name='Red Team', icon_url='http://www.lexicondesigns.com/images/other/ff_logo_red.png')
	await client.send_message(message.channel, embed=emb )
	
# Send a rich embeded messages instead of a plain ones
# to an individual user 	
async def send_emb_message_to_user(colour, embstr, message):
	emb = (discord.Embed(description=embstr, colour=colour))
	emb.set_author(name=client.user.name, icon_url=client.user.avatar_url)
	await client.send_message(message.author, embed=emb )

# send the server information to all of the players in a direct message
# send pickup game information to the channel 
async def send_information(blueTeam, redTeam, mappa, msg, serverID, serverPW):
	# set bot presence
	await client.change_presence(game=discord.Game(name='GLHF'))
	
	# send each user the server and password information
	redTeamMention = []
	blueTeamMention = []				
	emb = (discord.Embed(title="steam://connect/" + serverID + "/" + serverPW, colour=0x00ff00))
	emb.set_author(name=client.user.name, icon_url=client.user.avatar_url)
	for p in redTeam:
		await client.send_message(p, embed=emb )
		redTeamMention.append(p.mention)	# so we can mention all the members of the red team
	for p in blueTeam:
		await client.send_message(p, embed=emb )
		blueTeamMention.append(p.mention)	# so we can mention all the members of the blue team

	# Display the game information
	emb = (discord.Embed(title="The pickup is starting!!\nMap: " + mappa, colour=0x00ff00))
	emb.set_author(name=client.user.name, icon_url=client.user.avatar_url)
	await client.send_message(msg.channel, embed=emb )
	await send_emb_message_to_channel_blue("\n".join(map(str, blueTeamMention)), msg)	# Blue Team information				
	await send_emb_message_to_channel_red("\n".join(map(str, redTeamMention)), msg)		# Red Team information	
	
# Cycle through a user's roles to determine if they have admin access
# returns True if they do have access
async def user_has_access(author):
	if adminRoleID in [r.id for r in author.roles]: return True
	return False
	
# Every time we receive a message
@client.event
async def on_message(msg):
	global chosenMap
	global lastBlueTeam
	global lastMap
	global lastRedTeam
	global lasttime
	global mapMode
	global mapPicks
	global pickupRunning
	global players
	global randomTeams
	global rcon
	global rconPW	
	global serverID
	global serverPW
	global server_address
	global sizeOfGame
	global sizeOfTeams
	global selectionMode
	global starter
	global starttime
	global voteForMaps
	
	
	# the bot handles authorizing access to the pickup channel
	if msg.channel.id == requestChannelID: 
		if(msg.content.startswith(cmdprefix + "pug")):
			if(timeoutRoleID in [r.id for r in msg.author.roles]):
				# do not allow if they are in timeout
				role = discord.utils.get(msg.server.roles, id=timeoutRoleID)
				await send_emb_message_to_user(0xff0000, "I'm sorry, you cannot add to the pick-up channel while you are {0}. You will need to speak with a @Pug Admin for further details.".format(role.name), msg)
				return
			role = discord.utils.get(msg.server.roles, id=playerRoleID)
			while True:
				try:
					await client.add_roles(msg.author, role)
					await send_emb_message_to_user(0x00ff00, "Successfully added role {0}".format(role.name), msg)					
				except (discord.Forbidden, discord.HTTPException):
					continue
				break
		
		if(msg.content.startswith(cmdprefix + "unsubscribe") or msg.content.startswith(cmdprefix + "unpug")):
			role = discord.utils.get(msg.server.roles, id=playerRoleID)
			while True:
				try:
					await client.remove_roles(msg.author, role)
					await send_emb_message_to_user(0x00ff00, "Successfully removed role {0}".format(role.name), msg)					
				except (discord.Forbidden, discord.HTTPException):
					continue
				break
				
	if(msg.channel.id != singleChannelID and msg.server is not None): return	# only listen the the specified channel
			
	if msg.author == client.user: return			# talking to yourself isn't cool...even for bots

	# begin private message commands
	
	# PM's have None as server and return a User from message.author
	server = client.get_server(id=discordServerID)
	member = server.get_member(msg.author.id)
	
	# Add Alias - Adds a new alias to an existing map (read: row) to the maps collection (read: table) in the MongoDB 	
	if(msg.content.startswith(cmdprefix + "addalias") or msg.content.startswith(cmdprefix + "updatemap")):		
		# admin command
		if (await user_has_access(member)):
			message = msg.content.split()
			if(len(message) > 2):
				mpname = message[1]
				# get the new alaises
				aliases = []
				for alias in message[2:]:
					aliases.append(alias)
				# create the MongoDB client and connect to the database
				dbclient = pymongo.MongoClient(dbtoken)
				# first need to get the existing map and all of it's fields
				updated = dbclient.FortressForever.maps.find_one_and_update(filter={},query={ "$or":[{'name': mpname}, {'name': "ff_" + mpname}, {"aliases":mpname}] },
																		update={"$addToSet": {'aliases': { "$each": aliases } } },
																		return_document=ReturnDocument.AFTER)
				if(updated):
					await send_emb_message_to_user(0x00ff00, "Map has been updated in the database\n\n" + str(updated['name']) + "\n\nAliases: " + str(updated['aliases']), msg)
				else:
					await send_emb_message_to_user(0xff0000, "That map does not exist in the database. Did you mean to !addmap?", msg)
			else:
				await send_emb_message_to_user(0xff0000, msg.author.mention + "\n\nUsage: !addalias (!updatemap) <mapname_or_aliais> <**newalias1**> <**newalias2**> ... <**newaliasN**>\n\nPlease try again", msg)
		else:
			await send_emb_message_to_channel(0xff0000, msg.author.mention + " you do not have access to this command", msg)
			
	# Add Map - Adds a new map (read: row) to the maps collection (read: table) in the MongoDB 	
	if(msg.content.startswith(cmdprefix + "addmap")):		
		# admin command
		if (await user_has_access(member)):
			message = msg.content.split()
			if(len(message) > 1):
				# add the new map the MongoDB
				name = message[1]
				aliases = []
				for alias in message[2:]:
					aliases.append(alias)
				# create the MongoDB client and connect to the database
				dbclient = pymongo.MongoClient(dbtoken)
				cursor = dbclient.FortressForever.maps.find( { 'name' : name } )
				if cursor.count() == 0:
					# Mongo uses documents (key:value pairs) to represent rows of data
					dbclient.FortressForever.maps.insert([	{ 'name': name, 'aliases': aliases } ])

					# verify we have done this correctly
					last = dbclient.FortressForever.maps.find_one({'name':name})

					await send_emb_message_to_user(0x00ff00, "New map has been added to the database\n\n" + str(last), msg)
				else:
					await send_emb_message_to_user(0xff0000, "That map already exists in the database. Did you mean to !updatemap?", msg)
			else:
				await send_emb_message_to_user(0xff0000, msg.author.mention + "\n\nUsage: !addmap <name> <alias1> <alias2> ... <alias##>\n\nPlease try again", msg)
		else:
			await send_emb_message_to_channel(0xff0000, msg.author.mention + " you do not have access to this command", msg)
			
	# Add Server - Adds a new server (read: row) to the servers collection (read: table) in the MongoDB 	
	if(msg.content.startswith(cmdprefix + "addserver")):		
		# admin command
		if (await user_has_access(member)):
			message = msg.content.split()
			if(len(message) > 4):
				# add the new server the MongoDB
				name = message[1]
				passwd = message[2]
				rcon = message[3]
				serverid = message[4]
				# create the MongoDB client and connect to the database
				dbclient = pymongo.MongoClient(dbtoken)
				db = dbclient.FortressForever
	
				# Mongo uses documents (key:value pairs) to represent rows of data
				db.servers.insert([	{ 'names': [name], 'passwd': passwd, 'rcon': rcon, 'serverid': serverid } ])

				# verify we have done this correctly
				last = db.servers.find_one({'names':name})

				await send_emb_message_to_user(0x00ff00, "New server has been added to the database\n\n" + str(last), msg)
			else:
				await send_emb_message_to_user(0xff0000, msg.author.mention + "\n\nUsage: !addserver <name> <password> <rcon_password> <###.###.###.###:27015>\n\nPlease try again", msg)
		else:
			await send_emb_message_to_channel(0xff0000, msg.author.mention + " you do not have access to this command", msg)
	
	# # Delete Map - Removes an existing map (read: row) from the maps collection (read: table) in the MongoDB 	
	# if(msg.content.startswith(cmdprefix + "delmap")):		
		# # admin command
		# if (await user_has_access(member)):
			# # could make this more broad but I prefer to force exactness here
			# message = msg.content.split()
			# if(len(message) > 1):
				# # add the new server the MongoDB
				# name = message[1]
				# # create the MongoDB client and connect to the database
				# dbclient = pymongo.MongoClient(dbtoken)
				
				# # Mongo uses documents (key:value pairs) to represent rows of data
				# removed = dbclient.FortressForever.maps.remove([ { 'name': name } ])
				# if(len(removed) > 0):
					# print(removed)
					# await send_emb_message_to_user(0x00ff00, "Map has been removed from the database\n\n", msg)
				# else:
					# await send_emb_message_to_user(0xff0000, "I am sorry, but map was not found in the database\n\n", msg)
			# else:
				# await send_emb_message_to_user(0xff0000, msg.author.mention + "\n\nUsage: !delserver <name> <password> <rcon_password> <###.###.###.###:27015>\n\nYour entries must match exactly. Please try again", msg)
		# else:
			# await send_emb_message_to_channel(0xff0000, msg.author.mention + " you do not have access to this command", msg)
			
	# # Delete Server - Removes an existing server (read: row) from the servers collection (read: table) in the MongoDB 	
	# if(msg.content.startswith(cmdprefix + "delserver")):		
		# # admin command
		# if (await user_has_access(member)):
			# # could make this more broad but I prefer to force exactness here
			# message = msg.content.split()
			# if(len(message) > 4):
				# # add the new server the MongoDB
				# name = message[1]
				# passwd = message[2]
				# rcon = message[3]
				# serverid = message[4]
				# # create the MongoDB client and connect to the database
				# dbclient = pymongo.MongoClient(dbtoken)
				# db = dbclient.FortressForever

				# # Mongo uses documents (key:value pairs) to represent rows of data
				# removed = db.servers.remove([	{ 'names': [name], 'passwd': passwd, 'rcon': rcon, 'serverid': serverid } ])

				# await send_emb_message_to_user(0x00ff00, "Server has been removed from the database\n\n" + str(removed), msg)
			# else:
				# await send_emb_message_to_user(0xff0000, msg.author.mention + "\n\nUsage: !delserver <name> <password> <rcon_password> <###.###.###.###:27015>\n\nYour entries must match exactly. Please try again", msg)
		# else:
			# await send_emb_message_to_channel(0xff0000, msg.author.mention + " you do not have access to this command", msg)
			
	if(msg.server is None): return	# only listen for specific commands via direct message
	
	# Add - Adds the msg.author to the current pickup
	if(msg.content.startswith(cmdprefix + "add") and not msg.content.startswith(cmdprefix + "addalias") and not msg.content.startswith(cmdprefix + "addmap") and not msg.content.startswith(cmdprefix + "addserver")):
		# there must be an active pickup
		if(pickupRunning):
			# one can only add if:
			# 	they are not already added
			# 	we are not already selecting teams
			if(msg.author in players):
				await send_emb_message_to_channel(0xff0000, msg.author.mention + " you have already added to this pickup", msg)
				return
			elif(selectionMode):
				await send_emb_message_to_channel(0xff0000, msg.author.mention + " you cannot add once the pickup has begun", msg)
				return 
			elif(len(players) == sizeOfGame):
				await send_emb_message_to_channel(0xff0000, msg.author.mention + " sorry, the game is currently full\nYou will have to wait until the next one starts", msg)
				return 
			else:	# all clear to add them				
				# add to pool for easier notification
				role = discord.utils.get(msg.server.roles, id=poolRoleID)
				try:
					await client.add_roles(msg.author, role)
				except (discord.Forbidden, discord.HTTPException):
					pass
				players.append(msg.author)
				await send_emb_message_to_channel(0x00ff00, msg.author.mention + " you have been added to the pickup.\nThere are currently " + str(len(players)) + "/" + str(sizeOfGame) + " Players in the pickup", msg)
				await client.change_presence(game=discord.Game(name='Pickup (' + str(len(players)) + '/' + str(sizeOfGame) + ') ' + cmdprefix + 'add'))
			
			# each time someone adds, we need to check to see if the pickup is full
			if(len(players) == sizeOfGame):			
				# start the pickup
				reset = await go_go_gadget_pickup(mapMode, mapPicks, msg, selectionMode, starter, pickupRunning, players, poolRoleID, readyupChannelID, voteForMaps)
				if(reset):
					# Reset so we can play another one
					mapPicks = {}		
					players = []
					starter = []
					mapMode = True
					selectionMode = False
					pickupRunning = False
					voteForMaps = True
		else:
			await send_emb_message_to_channel(0xff0000, msg.author.mention + " you cannot use this command, there is no pickup running right now. Use " + adminRoleMention + " to request an admin start one for you", msg)
					
	# Admin - Displays the admin of the current pickup
	if(msg.content.startswith(cmdprefix + "admin")):
		# there must be an active pickup
		if(pickupRunning):
			await send_emb_message_to_channel(0x00ff00, "Game Admin is: " + starter[0].mention, msg)
		else:
			await send_emb_message_to_channel(0xff0000, msg.author.mention + " you cannot use this command, there is no pickup running right now. Use " + adminRoleMention + " to request an admin start one for you", msg)
		
	# Changelevel - Change the map in the server using the RCON commange changelevel
	if (msg.content.startswith(cmdprefix + "changelevel ") or msg.content.startswith(cmdprefix + "changemap ")):
		# admin command
		if (await user_has_access(msg.author)):
			message = msg.content.split()
			# make sure the user provided a map
			if(len(message) > 1):
				# check to see if the provided map is in the database
				atom = await mapname_is_valid(msg, message[1])
				if(atom != "INVALID"): 
					# change the map in the server to the provided map
					try:
						rcon.execute('changelevel ' + atom)
					except Exception:
						pass
					await send_emb_message_to_channel(0x00ff00, msg.author.mention + " the map has been changed to " + atom, msg)						
				else:
					await send_emb_message_to_channel(0xff0000, msg.author.mention + " that map is not in my !maplist. Please make another selection", msg)
					await list_all_the_maps(msg)
			else:
				await send_emb_message_to_user(0xff0000, msg.author.mention + " you must provide a mapname. " + cmdprefix + "changemap <mapname>", msg)
		else:
			await send_emb_message_to_channel(0xff0000, msg.author.mention + " you do not have access to this command", msg)
			
	# Commands - Prints the commands menu
	if(msg.content.startswith(cmdprefix + "commands")):
		emb = (discord.Embed(title="Player Commands:", description="FF Pickup Bot Commands accessible by all users", colour=0x00AE86))
		emb.set_author(name=client.user.name, icon_url=client.user.default_avatar_url)
		emb.add_field(name=cmdprefix + 'add', value='Adds yourself to the current pickup', inline=False)
		emb.add_field(name=cmdprefix + 'admin', value='Displays the admin of the current pickup', inline=False)
		emb.add_field(name=cmdprefix + 'commands', value='Prints this command menu', inline=False)
		emb.add_field(name=cmdprefix + 'demos', value='Provides you with a link to the currently stored demos', inline=False)
		emb.add_field(name=cmdprefix + 'hawking', value='Displays a random quote from the late Dr. S. W. Hawking', inline=False)
		emb.add_field(name=cmdprefix + 'journals', value='Displays a link to 55 papers written by Dr. Hawking in a peer-reviewed journal', inline=False)
		emb.add_field(name=cmdprefix + 'last', value='Displays information about the last pickup that was played', inline=False)
		emb.add_field(name=cmdprefix + 'listmaps', value='Provides you with a list of all the maps that are available for nomination', inline=False)
		emb.add_field(name=cmdprefix + 'map', value='Show the chosen map for the current pickup', inline=False)
		emb.add_field(name=cmdprefix + 'maps', value='Show the nominated maps for the current pickup', inline=False)
		emb.add_field(name=cmdprefix + 'maplist', value='Provides you with a list of all the maps that are available for nomination', inline=False)
		emb.add_field(name=cmdprefix + 'nominate', value='Nominate the specified map', inline=False)
		emb.add_field(name=cmdprefix + 'nominated', value='Show the nominated maps for the current pickup', inline=False)
		emb.add_field(name=cmdprefix + 'records', value='Provides you with a link to the All Time Records', inline=False)
		emb.add_field(name=cmdprefix + 'remove', value='Removes yourself from the pickup', inline=False)		
		emb.add_field(name=cmdprefix + 'sendinfo', value='Sends you the server IP and password', inline=False)
		emb.add_field(name=cmdprefix + 'teams', value='Displays current pickup info', inline=False)
		await client.send_message(msg.author, embed=emb)
		if (await user_has_access(msg.author)):
			emb = (discord.Embed(title="Admin Commands:", description="These commands are accessible only by the game admins", colour=0xffa500))
			emb.set_author(name=client.user.name, icon_url=client.user.default_avatar_url)
			emb.add_field(name=cmdprefix + 'changelevel <mapname>', value='Changes the map in the server via RCON', inline=False)
			emb.add_field(name=cmdprefix + 'end', value='End the current pickup (even if you did not start it)', inline=False)
			emb.add_field(name=cmdprefix + 'pickup', value='Start a new pickup game', inline=False)
			emb.add_field(name=cmdprefix + 'players <numberOfPlayers>', value='Change the number of players and the size of the teams', inline=False)
			emb.add_field(name=cmdprefix + 'remove @player', value='Removes the player you specified from the pickup', inline=False)
			emb.add_field(name=cmdprefix + 'removenom <mapname>', value='Removes the map nomination you specified from the pickup', inline=False)
			emb.add_field(name=cmdprefix + 'setmode <random/vote>', value='Change the way the map is chosen, options are random or vote (Game Starter Only)', inline=False)
			emb.add_field(name=cmdprefix + 'setserver <name/server> <alias/serverID>', value='Change the server the pickup will be played on (Game Starter Only)', inline=False)
			emb.add_field(name=cmdprefix + 'transfer @admin', value='Give your pickup to another admin (Game Starter) or take possesion of another admins pickup (All Other Admins)', inline=False)
			emb.add_field(name=cmdprefix + 'veto', value='Stop another admin from using !end or !transfer on your pickup', inline=False)
			await client.send_message(msg.author, embed=emb)
			# Private Message Commands
			emb = (discord.Embed(title="Private Message Commands:", description="These admin commands further require they be sent as a direct message (read: here and not in the channel)\n\n*Pay special **attention** as these will directly modify the Mongo Database*", colour=0xff0000))			
			emb.add_field(name=cmdprefix + 'addalias <mapname_or_aliais> <**newalias1**> <**newalias2**> ... <**newaliasN**>', value='Adds new alias(es) to an existing map (read: row) to the maps collection (read: table) in the MongoDB', inline=False)
			emb.add_field(name=cmdprefix + 'addmap <name> <alias1> <alias2> ... <alias##>', value='Adds a new map (read: row) to the maps collection (read: table) in the MongoDB\n\nAliases are optional', inline=False)
			emb.add_field(name=cmdprefix + 'addserver <name> <password> <rcon_password> <###.###.###.###:27015>', value='Adds a new server (read: row) to the servers collection (read: table) in the MongoDB', inline=False)
			# emb.add_field(name=cmdprefix + 'delmap <name>', value='Deletes an existing map (read: row) from the maps collection (read: table) in the MongoDB', inline=False)
			# emb.add_field(name=cmdprefix + 'delserver <name> <password> <rcon_password> <###.###.###.###:27015>', value='Deletes an existing server (read: row) from the servers collection (read: table) in the MongoDB\n\nYour entries must match **exactly**', inline=False)
			emb.add_field(name=cmdprefix + 'updatemap <mapname_or_aliais> <**newalias1**> <**newalias2**> ... <**newaliasN**>', value='Adds new alias(es) to an existing map (read: row) to the maps collection (read: table) in the MongoDB', inline=False)
			await client.send_message(msg.author, embed=emb)
			
	# Demos - Provides the msg.author with a link to the currently stored demos via direct message
	if(msg.content.startswith(cmdprefix + "demos")): await send_emb_message_to_user(0x00AE86, "SourceTV demos can be found here: http://www.ffpickup.com/?p=demos", msg)
		
	# End - End the current pickup
	if(msg.content.startswith(cmdprefix + "end")):
		# there must be an active pickup
		if(pickupRunning):
			# admin command
			if (await user_has_access(msg.author)):
				# only end if admin is game_starter or game_starter does not !veto in time
				if(starter[0] == msg.author or not await check_for_veto(cmdprefix + "end", msg, starter[0])):
					mapPicks.clear()
					role = discord.utils.get(msg.server.roles, id=poolRoleID)
					for p in players:
						try:
							await client.remove_roles(p, role)
						except Exception:
							pass
					del players[:]
					del starter[:]
					selectionMode = False
					pickupRunning = False
					await send_emb_message_to_channel(0x00ff00, "The pickup has been ended by an admin", msg)
					await client.change_presence(game=discord.Game(name=' '))
				else:
					await send_emb_message_to_channel(0xff0000, starter[0].mention + " has vetoed the command", msg)
			else:
				await send_emb_message_to_channel(0xff0000, msg.author.mention + " you do not have access to this command", msg)
		else:
			await send_emb_message_to_channel(0xff0000, msg.author.mention + " you cannot use this command, there is no pickup running right now. Use " + adminRoleMention + " to request an admin start one for you", msg)
	
	# Hawking - Displays a random quote from The Great Dr. Hawking
	if(msg.content.startswith(cmdprefix + "hawking")):
		quote, source = choice(list(quotes.items()))
		emb = (discord.Embed(description=quote, colour=0x5e7750))
		emb.set_author(name="Dr. Stephen William Hawking, 1942-2018", icon_url=client.user.avatar_url)
		emb.add_field(name='Source:', value=source, inline=False)
		await client.send_message(msg.channel, embed=emb )
		
	# Journals - 	Displays a link to 55 papers in Physical Review D and Physical Review Letters
	#				Gathered together and made public by the American Physical Society 
	if(msg.content.startswith(cmdprefix +  "journals")):		
		emb = (discord.Embed(description='''To mark the passing of Stephen Hawking, the American Physical Society have gathered together and made free to read his 55 papers in the peer-reviewed, scientific journals Physical Review D and Physical Review Letters.''', colour=0x5e7750))
		emb.set_author(name="Dr. Stephen William Hawking, 1942-2018", icon_url=client.user.avatar_url)
		emb.add_field(name='Link:', value='https://journals.aps.org/collections/stephen-hawking', inline=False)
		await client.send_message(msg.channel, embed=emb)
		
	# Last - Displays information about the last pickup that was played
	if(msg.content.startswith(cmdprefix + "last")):
		# get the last pickup information from the MongoDB
		found = db.pickups.find_one({'last':True})
		lastBlueTeam = found.get('blueteam')
		lastRedTeam = found.get('redteam')
		lastMap = found.get('map')
		lasttime = found.get('time')
	
		# set up the timedelta
		elapsedtime = time.time() - lasttime
		td = timedelta(seconds=elapsedtime)
		td = td - timedelta(microseconds=td.microseconds)
		
		# we have to send these as multiple embed messages
		# if we try to send more than 2000 characters discord raises a 400 request error
		emb = (discord.Embed(title="Last Pickup was " + str(td) + " ago on " + lastMap, colour=0x00ff00))
		emb.set_author(name=client.user.name, icon_url=client.user.avatar_url)
		await client.send_message(msg.channel, embed=emb )
		await send_emb_message_to_channel_blue("\n".join(map(str, lastBlueTeam)), msg)
		await send_emb_message_to_channel_red("\n".join(map(str, lastRedTeam)), msg)
				
	# Map (but not maps or maplist) - Show the chosen map for the current pickup
	if (msg.content.startswith(cmdprefix + "map") and not msg.content.startswith(cmdprefix + "maps") and not msg.content.startswith(cmdprefix + "maplist")):
		# there must be an active pickup
		if(pickupRunning):
			# only allow if pickup selection has already begun
			if(selectionMode):
				await send_emb_message_to_channel(0x00ff00, "The map for this pickup is " + chosenMap, msg)				
			else:
				await send_emb_message_to_channel(0xff0000, msg.author.mention + " you cannot see the map until the pickup has begun", msg)
		else:
			await send_emb_message_to_channel(0xff0000, msg.author.mention + " you cannot use this command, there is no pickup running right now. Use " + adminRoleMention + " to request an admin start one for you", msg)
			
	# Maps or Nominated - Show the nominated maps for the current pickup
	if (msg.content.startswith(cmdprefix + "maps") or msg.content.startswith(cmdprefix + "nominated")):
		# there must be an active pickup
		if(pickupRunning):
			# need to build the list of maps
			mapStr = ""
			for k in mapPicks:
				mapStr = mapStr + str(mapPicks[k]) + " (" + k.mention + ")\n"			
			await send_emb_message_to_channel(0x00ff00, "Current Maps (" + str(len(mapPicks)) + "/" + str(sizeOfMapPool) + ")\n" + mapStr, msg)
		else:
			await send_emb_message_to_channel(0xff0000, msg.author.mention + " you cannot use this command, there is no pickup running right now. Use " + adminRoleMention + " to request an admin start one for you", msg)
			
	# Maplist - Provides the msg.author with a list of all the maps that are available for nomination via direct message
	if (msg.content.startswith(cmdprefix + "maplist") or msg.content.startswith(cmdprefix + "listmaps")): 
		await list_all_the_maps(msg)		
		
	# Nominate - Nominate the specified map
	if(msg.content.startswith(cmdprefix + "nominate ")):
		# there must be an active pickup
		if(pickupRunning):
			# only allow if pickup has not already begun
			if(selectionMode and not mapMode):
				await send_emb_message_to_channel(0xff0000, msg.author.mention + " you cannot nominate maps once the pickup has begun", msg)
			else:
				# must also be added to the current pickup
				if(msg.author in players):
					message = msg.content.split()
					# make sure the user provided a map
					if(len(message) > 1):
						# check to see if the provided map is valid
						atom = await mapname_is_valid(msg, message[1])
						if(atom != "INVALID"): 
							# check to see if someone else noimated this map 
							for a, mp in mapPicks.items():
								if(atom == str(mp)):
									await send_emb_message_to_channel(0xff0000, msg.author.mention + " that map has already been nominated. Please make another selection", msg)
									return # break out if duplicate nomination
									
							# only allow a certain number of maps
							if(len(mapPicks) < sizeOfMapPool or msg.author in mapPicks):
								# users may only nominate one map
								mapPicks.update({msg.author:atom})
								await send_emb_message_to_channel(0x00ff00, msg.author.mention + " has nominated " + atom, msg)
							else:
								# need to build the list of maps
								mapStr = ""
								for k in mapPicks:
									mapStr = mapStr + str(mapPicks[k]) + " (" + k.mention + ")\n"
								emb = (discord.Embed(description=msg.author.mention + " there is already more than " + str(sizeOfMapPool) + " maps nominated", colour=0xff0000))
								emb.set_author(name=client.user.name, icon_url=client.user.avatar_url)
								emb.add_field(name='Current Maps', value=mapStr, inline=False)
								await client.send_message(msg.channel, embed=emb )							
						else:
							await send_emb_message_to_channel(0xff0000, msg.author.mention + " that map is not in my !maplist. Please make another selection", msg)
							await list_all_the_maps(msg)
					else:
						await send_emb_message_to_user(0xff0000, msg.author.mention + " you must provide a mapname. " + cmdprefix + "nominate <mapname>", msg)
				else:
					await send_emb_message_to_channel(0xff0000, msg.author.mention + " you cannot use this command, you must be added to the pickup to nominate maps", msg)
		else:
			await send_emb_message_to_channel(0xff0000, msg.author.mention + " you cannot use this command, there is no pickup running right now. Use " + adminRoleMention + " to request an admin start one for you", msg)
			
	# Pickup - Start a new pickup game
	if(msg.content.startswith(cmdprefix + "pickup")):
		# admin command
		if (await user_has_access(msg.author)):
			# only start one if there is not already one running	
			if(pickupRunning):
				await send_emb_message_to_channel(0xff0000, "There is already a pickup running. " + cmdprefix + "teams to see the game details", msg)
			else:
				pickupRunning = True
				starter.append(msg.author)
				await send_emb_message_to_channel(0x00ff00, "A pickup has been started. " + cmdprefix + "add to join up.", msg)
				await client.change_presence(game=discord.Game(name='Pickup (' + str(len(players)) + '/' + str(sizeOfGame) + ') ' + cmdprefix + 'add'))
				starttime = time.time()
		else:
			await send_emb_message_to_channel(0xff0000, msg.author.mention + " you do not have access to this command", msg)
			
	# Players - Change the number of players and the size of the teams
	if(msg.content.startswith(cmdprefix + "players")):
		# there must be an active pickup
		if(pickupRunning):
			# admin command
			if (await user_has_access(msg.author)):
				# make sure this admin owns this pickup
				if(starter[0] == msg.author):
					if(selectionMode):
						await send_emb_message_to_channel(0xff0000, msg.author.mention + " you cannot change the sizes once the pickup has begun", msg)
					else:
						message = msg.content.split()
						if(len(message) == 1):
							await send_emb_message_to_user(0xff0000, "You must provide a new size " + cmdprefix + "players <numberOfPlayers>", msg)
						else:
							# make sure the msg.author is giving an integer value
							while True:
								try:
									sz = int(message[1])
									if(sz == 0):
										# zero players? Just end it then
										await send_emb_message_to_channel(0xff0000, msg.author.mention + " you cannot change to zero players, please use " + cmdprefix + "end instead", msg)
									elif((sz % 2) == 0):
										# even number
										if(sz < len(players)):
											# do not lower sizes if more players have added already
											await send_emb_message_to_channel(0xff0000, msg.author.mention + " the player pool is too big to change to that value", msg)
										else:
											sizeOfTeams = int(sz/2)
											sizeOfGame = int(sz)
											await send_emb_message_to_channel(0x00ff00, msg.author.mention + " the size of the game has been changed to " + str(sz), msg)
									else:
										# odd number
										await send_emb_message_to_channel(0xff0000, msg.author.mention + " the size of the teams must be even", msg)
								except(ValueError):
									continue
								break
				else:
					await send_emb_message_to_channel(0xff0000, msg.author.mention + " sorry, this pickup does not belong to you, it belongs to " + starter[0].mention, msg)
			else:
				await send_emb_message_to_channel(0xff0000, msg.author.mention + " you do not have access to this command", msg)
		else:
			await send_emb_message_to_channel(0xff0000, msg.author.mention + " you cannot use this command, there is no pickup running right now. Use " + adminRoleMention + " to request an admin start one for you", msg)
			
	# Records - Provides msg.author with a link to the All Time Records
	if(msg.content.startswith(cmdprefix + "records")): await send_emb_message_to_user(0x00ff00, "All-time Records (work in progress): http://parser.ffpickup.com/v2/records/", msg)		
		
	# Remove - Removes msg.author and their map nomination from the pickup
	if (msg.content.startswith(cmdprefix + "remove") and not msg.content.startswith(cmdprefix + "removenom")):
		# there must be an active pickup
		if(pickupRunning):
			if(selectionMode is False):
				try:
					idleUser = msg.mentions[0]
					# must be an admin to remove someone other than yourself
					if(await user_has_access(msg.author)):
						if(idleUser in players):
							players.remove(idleUser)		# remove from players list
							mapPicks.pop(idleUser, None)	# remove this players nomination if they had one
							role = discord.utils.get(msg.server.roles, id=poolRoleID)
							try:
								await client.remove_roles(msg.mentions[0], role)
							except Exception:
								pass
							await send_emb_message_to_channel(0x00ff00, idleUser.mention + " you have been removed from the pickup by " + msg.author.mention + " (admin)", msg)
							await client.change_presence(game=discord.Game(name='Pickup (' + str(len(players)) + '/' + str(sizeOfGame) + ') ' + cmdprefix + 'add'))
						else:
							await send_emb_message_to_channel(0x00ff00, msg.author.mention + " that user is not added to the pickup", msg)
					else:
						await send_emb_message_to_channel(0xff0000, msg.author.mention + " you do not have access to this command", msg)
				except(IndexError):
					# no user mentioned so check if the author is in pickup 
					if(msg.author in players):
						players.remove(msg.author)		# remove from players list
						mapPicks.pop(msg.author, None)	# remove this players nomination if they had one
						role = discord.utils.get(msg.server.roles, id=poolRoleID)
						try:
							await client.remove_roles(msg.author, role)
						except Exception:
							pass
						await send_emb_message_to_channel(0x00ff00, msg.author.mention + " you have been removed from the pickup", msg)
						await client.change_presence(game=discord.Game(name='Pickup (' + str(len(players)) + '/' + str(sizeOfGame) + ') ' + cmdprefix + 'add'))
					else:
						await send_emb_message_to_channel(0x00ff00, msg.author.mention + " no worries, you never even added", msg)
			else:	
				# selectionMode is True
				await send_emb_message_to_channel(0xff0000, msg.author.mention + " you cannot use !remove once the pickup has begun", msg)
		else:
			await send_emb_message_to_channel(0xff0000, msg.author.mention + " you cannot use this command, there is no pickup running right now. Use " + adminRoleMention + " to request an admin start one for you", msg)
	
	# Remove Nomination - Removes the specified map nomination from the pickup
	if (msg.content.startswith(cmdprefix + "removenom")):
		# there must be an active pickup
		if(pickupRunning):
			if(selectionMode is False):
				# must be an admin to remove a map nomination
				if(await user_has_access(msg.author)):
					message = msg.content.split()
					# make sure the user provided a map
					if(len(message) > 1):
						# check to see if the provided map is an alias
						atom = await mapname_is_valid(msg, message[1])
						if(atom != "INVALID"):
							# check to see if someone has noimated this map 
							for author, mp in mapPicks.items():
								if(atom == str(mp)):
									# remove this nomination
									mapPicks.pop(author, None)
									await send_emb_message_to_channel(0x00ff00, atom + " has been removed from the nominations by " + msg.author.mention + " (admin)", msg)
									return 
						else:
							await send_emb_message_to_channel(0xff0000, msg.author.mention + " that map is not in my !maplist. Please make another selection", msg)
					else:
						await send_emb_message_to_user(0xff0000, msg.author.mention + " you must provide a mapname. " + cmdprefix + "removenom <mapname>", msg)
				else:
					await send_emb_message_to_channel(0xff0000, msg.author.mention + " you do not have access to this command", msg)
			else:	
				# selectionMode is True
				await send_emb_message_to_channel(0xff0000, msg.author.mention + " you cannot use !removenom once the pickup has begun", msg)
		else:
			await send_emb_message_to_channel(0xff0000, msg.author.mention + " you cannot use this command, there is no pickup running right now. Use " + adminRoleMention + " to request an admin start one for you", msg)
			
	# Setmode - Change the way the map is picked
	if (msg.content.startswith(cmdprefix + "setmode")):
		# there must be an active pickup
		if(pickupRunning):
			# admin command
			if (await user_has_access(msg.author)):
				# make sure this admin owns this pickup
				if(starter[0] == msg.author):
					message = msg.content.split()
					# check for a pick and catch it if they don't mention a valid mode				
					try:
						m = message[1]
						if(m.startswith("random")):
							voteForMaps = False
							await send_emb_message_to_channel(0x00ff00, "Map Selection has successfully been changed to randomly select from the list of nominations", msg)
						elif(m.startswith("vote")):
							voteForMaps = True
							await send_emb_message_to_channel(0x00ff00, "Map Selection has successfully been changed to call a player vote", msg)
						else:
							await send_emb_message_to_channel(0xff0000, msg.author.mention + " that is not a valid mode you must type !setmode random or !setmode vote", msg)
							return
					except(IndexError):
						await send_emb_message_to_channel(0xff0000, msg.author.mention + " to change the map selection mode you must type !setmode random or !setmode vote", msg)
						return
				else:
					await send_emb_message_to_channel(0xff0000, msg.author.mention + " sorry, this pickup does not belong to you, it belongs to " + starter[0].mention, msg)
			else:
				await send_emb_message_to_channel(0xff0000, msg.author.mention + " you do not have access to this command", msg)
		else:
			await send_emb_message_to_channel(0xff0000, msg.author.mention + " you cannot use this command, there is no pickup running right now. Use " + adminRoleMention + " to request an admin start one for you", msg)	
		
	# Setserver - Change the server the pickup will be played on 
	if (msg.content.startswith(cmdprefix + "setserver")):
		# there must be an active pickup
		if(pickupRunning):
			# admin command
			if (await user_has_access(msg.author)):
				# make sure this admin owns this pickup
				if(starter[0] == msg.author):
					message = msg.content.split()
					if(len(message) > 2):
						# switch on flag and search the MongoDB for a document that contains that op:data
						op = message[1]
						data = message[2]

						# create the MongoDB client and connect to the database
						dbclient = pymongo.MongoClient(dbtoken)
						# switch on op
						if(op == "name"):
							cursor = dbclient.FortressForever.servers.find( { 'names' : data } )
						elif(op == "server"):
							cursor = dbclient.FortressForever.servers.find( { 'serverid' : data } )
						if cursor.count() > 0:
							for doc in cursor:
								# doc is a dict
								serverID = doc['serverid']
								serverPW = doc['passwd']
								rconPW = doc['rcon']
								server_address = (serverID[:-6], 27015)
								# Setup an new RCON connection 
								rcon = valve.rcon.RCON(server_address, rconPW)
								rcon.connect()
								rcon.authenticate()
								await send_emb_message_to_user(0x00ff00, msg.author.mention + " changing server\n\nServerID: " + serverID + "\n\nServer Address: " + str(server_address) + "\n\nPassword: " + serverPW + "\n\nRCON: " + rconPW, msg)
						else:
							await send_emb_message_to_user(0xff0000, msg.author.mention + " I am sorry, I did not find a server matching " + op + " = " + data + "\n\nPlease try again", msg)
					else:
						await send_emb_message_to_user(0xff0000, msg.author.mention + "\n\nUsage: !setserver <name/server> <alias/serverID>\n\nPlease try again", msg)
				else:
					await send_emb_message_to_channel(0xff0000, msg.author.mention + " sorry, this pickup does not belong to you, it belongs to " + starter[0].mention, msg)
			else:
				await send_emb_message_to_channel(0xff0000, msg.author.mention + " you do not have access to this command", msg)
		else:
			await send_emb_message_to_channel(0xff0000, msg.author.mention + " you cannot use this command, there is no pickup running right now. Use " + adminRoleMention + " to request an admin start one for you", msg)	
				
	# Sendinfo - Sends msg.author the server IP and password via direct message
	if(msg.content.startswith(cmdprefix + "sendinfo")): await send_emb_message_to_user(0x00ff00, "connect " + serverID + " " + serverPW, msg)
		
	# Teams - Displays current pickup information
	if(msg.content.startswith(cmdprefix + "teams")):
		# there must be an active pickup
		if(pickupRunning):
			if(len(players) < 1):
				await send_emb_message_to_channel(0x00ff00, "The pickup is empty right now. " + cmdprefix + "add to join", msg)					
			elif(len(players) > 0):
				plyrStr = '\n'.join([p.mention for p in players])
				await send_emb_message_to_channel(0x00ff00, "Players:\n" + plyrStr, msg)
		else:
			await send_emb_message_to_channel(0xff0000, msg.author.mention + " you cannot use this command, there is no pickup running right now. Use " + adminRoleMention + " to request an admin start one for you", msg)
			
	# Transfer - Give your pickup to another admin (Game Starter Only)
	if (msg.content.startswith(cmdprefix + "transfer")):
		# there must be an active pickup
		if(pickupRunning):
			# admin command
			if (await user_has_access(msg.author)):
				# make sure this admin owns this pickup
				if(starter[0] == msg.author):
					# check for a pick and catch it if they don't mention an available player				
					while True:
						try:
							newCap = msg.mentions[0]
						except(IndexError):
							await send_emb_message_to_channel(0x00ff00, msg.author.mention + " you must type !transfer @nameOfAdmin to transfer your pickup.", msg)
							return	# break out if they did not specify a user
						break
						
					if(await user_has_access(newCap)):
						starter = []
						starter.append(newCap)
						await send_emb_message_to_channel(0x00ff00, msg.author.mention + " your pickup has successfully been transfered to " + msg.mentions[0].mention, msg)
					else:
						await send_emb_message_to_channel(0xff0000, msg.author.mention + " you can only transfer your pickup to another admin", msg)
				else:
					# check for a pick and catch if they mention another player				
					while True:
						try:
							newCap = msg.mentions[0]
							await send_emb_message_to_channel(0xff0000, msg.author.mention + " you may only transfer your own pickup to another player", msg)
							return # break out if they accidentally specify a user
						except(IndexError):
							break
					# otherwise some other admin is trying to transfer (read: take) this pickup
					if(not await check_for_veto(cmdprefix + "transfer", msg, starter[0])):
						await send_emb_message_to_channel(0x00ff00, msg.author.mention + " you have successfully taken possesion of " + starter[0].mention + " pickup", msg)
						starter = []
						starter.append(msg.author)
					else:
						await send_emb_message_to_channel(0xff0000, starter[0].mention + " has vetoed the transfer", msg)
			else:
				await send_emb_message_to_channel(0xff0000, msg.author.mention + " you do not have access to this command", msg)
		else:
			await send_emb_message_to_channel(0xff0000, msg.author.mention + " you cannot use this command, there is no pickup running right now. Use " + adminRoleMention + " to request an admin start one for you", msg)			
			
	# Unsubscribe - Allows users to leave the notification group with removes them from the channel
	if(msg.content.startswith(cmdprefix + "unsubscribe") or msg.content.startswith(cmdprefix + "unpug")):
			role = discord.utils.get(msg.server.roles, id=playerRoleID)
			while True:
				try:
					await client.remove_roles(msg.author, role)
					await send_emb_message_to_user(0x00ff00, "Successfully removed role {0}".format(role.name), msg)					
				except (discord.Forbidden, discord.HTTPException):
					continue
				break

# Run the bot
client.run(token)
