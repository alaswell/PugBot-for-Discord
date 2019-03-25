# Pickup Game Bot for use with discord
# Modified by: Alex Laswell for use with Fortress Forever
# Based on:
#	PugBot-for-Discord by techlover1 https://github.com/techlover1/PugBot-for-Discord

import asyncio
import config
from collections import OrderedDict
from datetime import timedelta
import discord
from discord import Game
from discord.ext.commands import Bot
import pymongo
from pymongo.collection import ReturnDocument
import random
from random import choice, shuffle
import re
import requests
import time
import valve.rcon

# Configurable constants
adminChannelID = config.adminChannelID
adminRoleID = config.adminRoleID
adminRoleMention = config.adminRoleMention
bannedChannelID = config.bannedChannelID
blueteamChannelID = config.blueteamChannelID
cmdprefix = config.cmdprefix
dbtoken = config.dbtoken
discordServerID = config.discordServerID
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
server_address = config.server_address
serverID = config.serverID
serverIDRegEx = config.serverIDRegEx
serverPattern = config.serverPattern
serverPW = config.serverPW
singleChannelID = config.singleChannelID
sizeOfGame = config.sizeOfGame
sizeOfTeams = config.sizeOfTeams
sizeOfMapPool = config.sizeOfMapPool
timeoutRoleID = config.timeoutRoleID
token = config.token
vipPlayerID = config.vipPlayerID

# Globals
BLUE_TEAM = []
CHOSEN_MAP = []
LAST_BLUE_TEAM = []
LAST_MAP = []
LAST_RED_TEAM = []
LAST_TIME = time.time()
MAP_PICKS = {}
PLAYERS = []
RED_TEAM = []
START_TIME = time.time()
STARTER = []
PICKUP_RUNNING= False
RANDOM_TEAMS = False
VOTE_FOR_MAPS = True

# the bot, client, and server objects
Bot = Bot(command_prefix=cmdprefix)
client = discord.Client()
server = None
adminRole = None
accessRole = None
poolRole = None
timeoutRole = None

# create the MongoDB client and connect to the database
dbclient = pymongo.MongoClient(dbtoken)
database = dbclient.FortressForever

# a valve RCON (Remote CONnection)
rcon = valve.rcon.RCON(server_address, rconPW)
rcon.connect()
rcon.authenticate()


#
# Functions A-Z
#


# do not allow if the author is in a timeout
async def author_is_in_timeout(message):
    global server
    member = server.get_member(message.author.id)
    if (timeoutRoleID in [r.id for r in member.roles]):
        emb = (discord.Embed(description="I'm sorry, you cannot use any of these commands while you are in timeout. You will need to speak with a " + adminRoleMention + " for further details.", colour=0xff0000))
        emb.set_author(name=Bot.user.name, icon_url=Bot.user.avatar_url)
        await Bot.send_message(message.author, embed=emb)
        return True
    return False


# Select the BLUE_TEAM
async def blue_team_picks(caps, context, playerPool):
    global BLUE_TEAM, RED_TEAM, PLAYERS, server
    playerPicked = False
    await send_emb_message_to_channel(0x00ff00, caps[0].mention + " type @player to pick. Available players are:\n\n" + '\n'.join([p.mention for p in playerPool]), context)

    while not playerPicked:
        # check for a pick and catch it if they don't mention an available player
        try:
            inputobj = await Bot.wait_for_message(author=server.get_member(caps[0].id))
            picked = inputobj.mentions[0]

            # If the player is in players and they are not already picked, add to the team
            if (picked in PLAYERS):
                if (picked not in RED_TEAM and picked not in BLUE_TEAM):
                    BLUE_TEAM.append(picked)
                    playerPool.remove(picked)
                    playerPicked = True
                    await send_emb_message_to_channel_blue(picked.mention + " has been added to the team", context)
                else:
                    await send_emb_message_to_channel(0xff0000, picked.mention + " is already on a team", context)
            else:
                await send_emb_message_to_channel(0xff0000, picked.mention + " is not in this pickup", context)
        except(IndexError):
            pass


async def check_bans():
    global bannedChannelID, accessRole, database, dbclient, server, timeoutRole

    while not Bot.is_closed:
        try:
            # reconnect to MongoDB
            await set_database()
            collection = database['banned']
            cursor = collection.find({})
            for document in cursor:
                origin = document.get('origin')
                length = document.get('length')
                elapsed_time = time.time() - origin
                if elapsed_time >= length:
                    # timeout has elapsed, give user back access
                    member = server.get_member(document.get('userid'))
                    try:
                        await Bot.remove_roles(member, timeoutRole)
                        await asyncio.sleep(2)
                        await Bot.add_roles(member, accessRole)
                    except Exception:
                        pass

                    # delete the ban from the MongoDB
                    collection.delete_one(document)
                    # notify the admins
                    emb = (discord.Embed(description="The ban for user " + member.mention + " has expired. They have been granted access to the channel once again", colour=0x00ff00))
                    emb.set_author(name=Bot.user.name, icon_url=Bot.user.avatar_url)
                    await Bot.send_message(server.get_channel(bannedChannelID), embed=emb)
                    # notify the user
                    emb = (discord.Embed(description="Your ban time has expired. You have been granted access to the bot and the channel once again", colour=0x00ff00))
                    emb.set_author(name=Bot.user.name, icon_url=Bot.user.avatar_url)
                    await Bot.send_message(member, embed=emb)
                    print("LOG MESSAGE: The ban for Player: " + str(member) + " has been removed by the bot")
            dbclient.close()
            await asyncio.sleep(600)  # 10 minutes
        except:
            pass # we can ignore an error when checking this once in a while

        
# check that the admin who started the game is still here
async def check_for_afk_admin():
    global adminRoleID, cmdprefix, STARTER
    # check for advanced filtering
    def check(msg):
        if (adminRoleID in [r.id for r in msg.author.roles]):
            return msg.content.startswith(cmdprefix + 'here')

    inputobj = await Bot.wait_for_message(timeout=durationOfCheckin, check=check)
    # wait_for_message returns 'None' if asyncio.TimeoutError thrown
    if (inputobj != None):  # game_starter did !checkin
        if inputobj.author != STARTER[0]:
            # another admin has stepped in
            STARTER = []
            STARTER.append(inputobj.author)
        return True
    else:  # game_starter did not !checkin
        return False


# cycle through the all the players in the pool and verify they are ready
async def check_for_afk_players():
    global PLAYERS, readyupChannelID, server
    ready_channel = discord.utils.get(server.channels, id=readyupChannelID)
    ready_users = ready_channel.voice_members
    afk_players = []

    # only preform this check if the readyupChannelID is a valid voice channel
    if (ready_channel is not None):
        # check to verify if each player is in the ready-up channel
        for p in PLAYERS:
            if (p not in ready_users):
                afk_players.append(p)  # add to missing players list
    return afk_players


async def check_for_map_nominations(context):
    global cmdprefix, MAP_PICKS, sizeOfGame, sizeOfMapPool, PICKUP_RUNNING, PLAYERS
    while(len(MAP_PICKS) < sizeOfMapPool and PICKUP_RUNNING and len(PLAYERS) == sizeOfGame):
        # need to build the list of maps
        mapStr = ""
        for k in MAP_PICKS:
            mapStr = mapStr + str(MAP_PICKS[k]) + " (" + k.mention + ")\n"
        await send_emb_message_to_channel(0xff0000, "Players must nominate more maps before we can proceed\nCurrently Nominated Maps (" + str(len(MAP_PICKS)) + "/" + str(sizeOfMapPool) + ")\n" + mapStr, context)
        async def needMapPicks(msg):					
            # check function for advanced filtering
            def check(msg):
                return msg.content.startswith(cmdprefix + 'nominate')
            # wait until someone nominates another map
            await Bot.wait_for_message(timeout=30, check=check)
        await needMapPicks(context.message)
            

# allows the game_starter to veto admin commands
async def check_for_veto(command, context):
    global cmdprefix, STARTER
    # generic check to allow game_starter to !veto another admin's command
    await send_emb_message_to_channel(0xff0000, STARTER[0].mention + "\n\n" + context.message.author.mention + " is trying to " + command + " your pickup. You have " + str(durationOfVeto) +
                                      " seconds to " + cmdprefix + "veto them, or the command will happen", context)
    # check for advanced filtering
    def check(msg):
        return msg.content.lower().startswith(cmdprefix + 'veto')

    inputobj = await Bot.wait_for_message(timeout=durationOfVeto, author=STARTER[0], check=check)
    # wait_for_message returns 'None' if asyncio.TimeoutError thrown
    if (inputobj != None):  # game_starter did !veto the command
        return True
    else:  # game_starter did not !veto
        return False


# Check to see if the message has been sent via a Direct Message to the bot
async def command_is_in_wrong_channel(context):
    global requestChannelID, singleChannelID
    if context.command.name == 'pug':
        if context.message.channel.id != requestChannelID:
            # Bot only listens to the request channel when granting access
            await send_emb_message_to_channel(0xff0000, context.message.author.mention + " you cannot use this command in this channel. Retry inside the " + server.get_channel(requestChannelID).name + " channel", context)
            return True
        else:
            return False
    elif context.command.name == 'addserver' or context.command.name == 'delserver':
        # Bot only listens to these commands via direct message
        if context.message.server is not None:
            await send_emb_message_to_channel(0xff0000, context.message.author.mention + " this command will only work as a direct message to the bot", context)
            return True
        else:
            return False
    elif context.command.name == 'ban' or context.command.name == 'unban':
        # Admin channel commands
        if context.message.channel.id != adminChannelID:
            # Bot only listens to the request channel when granting access
            await send_emb_message_to_channel(0xff0000, context.message.author.mention + " you cannot use this command in this channel. Retry inside the " + server.get_channel(adminChannelID).name + " channel", context)
            return True
        else:
            return False
    elif context.message.channel.id != singleChannelID:
        # Bot only listens to one channel for all other commands
        await send_emb_message_to_channel(0xff0000, context.message.author.mention + " you cannot use this command in this channel. Retry inside the " + server.get_channel(singleChannelID).name + " channel", context)
        return True
    return False


async def count_votes_message_channel(tdelta, keys, context, votelist, votetotals):
    global sizeOfMapPool
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
    await send_emb_message_to_channel(0x00ff00, tmpstr + "\n" + str(durationOfMapVote - tdelta0.total_seconds()) + " seconds remaining", context)


async def go_go_gadget_pickup(context):
    global adminRole, BLUE_TEAM, CHOSEN_MAP, cmdprefix, durationOfReadyUp, MAP_PICKS, server, sizeOfGame, STARTER, PICKUP_RUNNING, PLAYERS, poolRole, poolRoleID, RANDOM_TEAMS, RED_TEAM, readyupChannelID, VOTE_FOR_MAPS
    afk_players = []
    BLUE_TEAM = []
    caps = []
    RED_TEAM = []
    playerPool = []
    counter = 0
    countdown = time.time()
    elapsedtime = time.time() - countdown
    inputobj = 0  # used to manipulate the objects from messages
    pick_captains_counter = 0
    ready_channel = discord.utils.get(context.message.server.channels, id=readyupChannelID)
    RANDOM_TEAMS = True  # if game starter does not change, will pick teams randomly from players list
    td = timedelta(seconds=elapsedtime)

    await send_emb_message_to_channel(0x00ff00, "The pickup is starting!!\n\n" + poolRole.mention + " join the " + ready_channel.name + " to signify you are present and ready", context)

    # set up the embeded message incase we need to message players
    emb = (discord.Embed(title="The pickup is starting!!\n\nJoin the " + ready_channel.name + " to signify you are present and ready", colour=0xff0000))
    emb.set_author(name=Bot.user.name, icon_url=Bot.user.avatar_url)
    # give the players time to ready-up
    while (td.total_seconds() < durationOfReadyUp):
        # only check every 5 seconds
        await asyncio.sleep(5)
        # loop through the channel and check to see if everyone has joined it or not
        afk_players = await check_for_afk_players()
        if (len(afk_players) > 0):
            afkstr = '\n'.join([p.mention for p in afk_players])
            elapsedtime = time.time() - countdown
            td = timedelta(seconds=elapsedtime)
            # only message everyone on every third iteration
            if ((counter % 3) == 0):
                await send_emb_message_to_channel(0xff0000, "Missing players:\n\n" + afkstr, context)
                for p in afk_players:
                    try:
                        await Bot.send_message(p, embed=emb)
                    except Exception:
                        pass
            counter += 1
        else:
            # all players in list are idle in channel and ready
            break

    # if afk_players has people in it, then those player(s) timed out
    if (len(afk_players) > 0):
        for idleUser in afk_players:
            PLAYERS.remove(idleUser)  # remove from players list
            MAP_PICKS.pop(idleUser, None)  # remove this players nomination if they had one
            try:
                await Bot.remove_roles(idleUser, poolRole)
            except Exception:
                pass
            await send_emb_message_to_channel(0xff0000, idleUser.mention + " has been removed from the pickup due to inactivity", context)
            await Bot.change_presence(game=discord.Game(name='Pickup (' + str(len(PLAYERS)) + '/' + str(sizeOfGame) + ') ' + cmdprefix + 'add'))
        return False  # break out if we remove a player

    await send_emb_message_to_channel(0x00ff00, "All players are confirmed ready!", context)

    # Verifying admin status if they have not already confirmed ready
    if STARTER[0] not in PLAYERS:
        await send_emb_message_to_channel(0xffa500, "Verifying that we have an admin\n\n" + STARTER[0].mention + " please reply with " + cmdprefix + "here so we can proceed", context)
        adminPresent = False
        while not adminPresent:
            adminPresent = await check_for_afk_admin()
            if not adminPresent:
                # do we have an admin in the pool we can give the pickup to
                for p in PLAYERS:
                    if (await user_has_access(p)):
                        # admin found : transfering pickup
                        await send_emb_message_to_channel(0xff0000, STARTER[0].mention + " seems to be missing\n\nTransfering the game to " + p.mention, context)
                        STARTER = []
                        STARTER.append(p)
                        adminPresent = True
                        break  # no need to find another admin
                if not adminPresent:
                    # try to private message the game_starter
                    emb = (discord.Embed(description="You did not reply with " + cmdprefix + "here and your pickup has been put on hold", colour=0xff0000))
                    emb.set_author(name=Bot.user.name, icon_url=Bot.user.avatar_url)
                    await Bot.send_message(STARTER[0], embed=emb)
                    # ping all admins to see if someone can take over
                    await send_emb_message_to_channel(0xff0000, adminRole.mention + " the admin who started this pickup seems to be missing. " + cmdprefix + "here and save the pickup", context)
    # adminPresent == True

    #
    # Begin the pickup
    #

    # Map Selection
    await Bot.change_presence(game=discord.Game(name='Map Selection'))

    if len(CHOSEN_MAP) > 0:
        verify_chosen_map_is_good(context)

    # do we have the right amount of map nominations
    if len(CHOSEN_MAP) == 0:
        await check_for_map_nominations(context)

    if not await pickup_is_full(context): return False  # exit go_go if someone has removed

    if len(CHOSEN_MAP) == 0:
        await pick_map(context)

    if not await pickup_is_full(context): return False # exit go_go if someone has removed

    # by having the game admin approve
    # we can make sure teams end up fair more often
    adminApproves = False
    while not adminApproves:
        # loop until the game starter makes a decision
        pick_captains_counter = 1  # tracks how many times the game_starter has been asked
        shuffle(PLAYERS)  # shuffle the player pool
        RANDOM_TEAMS = await pick_captains(caps, context)
        while (len(caps) < 2):
            if (len(PLAYERS) < sizeOfGame):
                if (len(PLAYERS) > 0):
                    # game is no longer full
                    await send_emb_message_to_channel(0xff0000, "ABORTING: The pickup is no longer full", context)
                    await Bot.change_presence(game=discord.Game(name='Pickup (' + str(len(PLAYERS)) + '/' + str(sizeOfGame) + ') ' + cmdprefix + 'add'))
                    return False
                else:
                    # game has been !ended
                    await Bot.change_presence(game=discord.Game(name=' '))
                    return True
            elif (pick_captains_counter > 2):
                # game_starter is afk ... pug will be ended
                await send_emb_message_to_channel(0xff0000, "This pickup has been abandoned by the admin and will now be ended\n\n" + adminRole.mention + " someone who is here, will need to start a new one", context)
                await Bot.change_presence(game=discord.Game(name=' '))
                return True
            else:
                RANDOM_TEAMS = await pick_captains(caps, context)
                pick_captains_counter += 1

        if not awaitpickup_is_full(context): return False  # exit go_go if someone has removed

        # set up the initial teams
        if (RANDOM_TEAMS):
            for i in range(0, sizeOfTeams):
                RED_TEAM.append(PLAYERS[i])
                BLUE_TEAM.append(PLAYERS[i + sizeOfTeams])
        else:
            BLUE_TEAM.append(caps[0])
            RED_TEAM.append(caps[1])

            # copy the player pool over
            for p in PLAYERS:
                if p not in caps:
                    playerPool.append(p)

        # Switch off picking until the teams are all full
        await Bot.change_presence(game=discord.Game(name='Team Selection'))

        # if teams are not already full:
        if (len(RED_TEAM) < sizeOfTeams and len(BLUE_TEAM) < sizeOfTeams):
            if not await pickup_is_full(context): return False  # exit go_go if someone has removed

            await send_emb_message_to_channel(0x00ff00, caps[0].mention + " vs " + caps[1].mention, context)
            # Blue captain picks first
            await blue_team_picks(caps, context, playerPool)
            if (len(playerPool) > 1):
                # only make the captain pick if they have a choice
                await red_team_picks(caps, context, playerPool)
            else:
                RED_TEAM.append(playerPool[0])
                await send_emb_message_to_channel_red(playerPool[0].mention + " has been added to the team", context)
            while (len(RED_TEAM) < sizeOfTeams and len(BLUE_TEAM) < sizeOfTeams):
                if not await pickup_is_full(context): return False  # exit go_go if someone has removed

                # Red captain gets two picks first round so start with red
                await red_team_picks(caps, context, playerPool)

                if not await pickup_is_full(context): return False  # exit go_go if someone has removed

                if (len(playerPool) > 1):
                    # only make the captain pick if they have a choice
                    await blue_team_picks(caps, context, playerPool)
                else:
                    BLUE_TEAM.append(playerPool[0])
                    await send_emb_message_to_channel_blue(playerPool[0].mention + " has been added to the team", context)
        # both teams are full
        # verify everything looks good
        await send_emb_message_to_channel_blue('\n'.join([p.mention for p in BLUE_TEAM]), context)  # Blue Team information
        await send_emb_message_to_channel_red('\n'.join([p.mention for p in RED_TEAM]), context)  # Red Team information
        await send_emb_message_to_channel(0xffa500, STARTER[0].mention + " these are the teams\n\nReply with " + cmdprefix + "accept to accept them or with " + cmdprefix + "repick and we can choose again", context)
        didChoose = False
        while not didChoose:
            # check for advanced filtering
            def check(msg):
                if (msg.content.startswith(cmdprefix + 'accept') or msg.content.startswith(cmdprefix + 'repick')): return True
                return False

            inputobj = await Bot.wait_for_message(timeout=durationOfCheckin, author=STARTER[0], check=check)
            # wait_for_message returns 'None' if asyncio.TimeoutError thrown
            if (inputobj != None):
                didChoose = True
                # switch on choice
                if (inputobj.content.startswith(cmdprefix + "accept")):
                    adminApproves = True
                elif (inputobj.content.startswith(cmdprefix + "repick")):
                    # reset so we can pick new teams
                    caps = []
                    BLUE_TEAM = []
                    playerPool = []
                    RED_TEAM = []
                    adminApproves = False
            else:
                didChoose = False
                await send_emb_message_to_channel(0xff0000, STARTER[0].mention + " please make a selection:\n\n" + cmdprefix + "accept to **accept** the teams\n\n" + cmdprefix + "repick to discard these teams and **repick** new ones", context)
    # adminApproves and everything is set

    # pm users and message server with game information
    await send_information(context)

    # change the map in the server to the chosen map
    try:
        rcon.execute('changelevel ' + CHOSEN_MAP)
    except Exception:
        pass

    # move the players to their respective voice channels
    for p in RED_TEAM:
        try:
            await Bot.move_member(p, Bot.get_channel(redteamChannelID))
        except(InvalidArgument, HTTPException, Forbidden):
            continue
    for p in BLUE_TEAM:
        try:
            await Bot.move_member(p, Bot.get_channel(blueteamChannelID))
        except(InvalidArgument, HTTPException, Forbidden):
            continue

    # Save all the information for !last
    await save_last_game_info()

    # remove the players from the pool
    await remove_everyone_from_pool_role(context)
    return True


# Lists all of the maps in the MongoDB table : maps
async def list_all_the_maps(msg):
    global database
    # find will return all documents in the maps collection
    foundmaps = database.maps.find({})
    # convert to a list so we can index into it
    maps = list(foundmaps)

    # with the aliases, this message gets big quickly so we
    # need to chunk up the maplist into sections to accomidate

    ## Part I   ##
    emb = (discord.Embed(description="Currently, you may nominate any of the following maps:", colour=0xffa500))
    emb.set_author(name=Bot.user.name, icon_url=Bot.user.avatar_url)
    for map in maps[:20]:
        emb.add_field(name=str(map['name']), value=str(map['aliases']), inline=False)
    await Bot.send_message(msg.author, embed=emb)
    ## Part II  ##
    emb = (discord.Embed(description="", colour=0xffa500))
    emb.set_author(name=Bot.user.name, icon_url=Bot.user.avatar_url)
    for map in maps[20:40]:
        emb.add_field(name=str(map['name']), value=str(map['aliases']), inline=False)
    await Bot.send_message(msg.author, embed=emb)
    ## Part III ##
    emb = (discord.Embed(description="", colour=0xffa500))
    emb.set_author(name=Bot.user.name, icon_url=Bot.user.avatar_url)
    for map in maps[40:60]:
        emb.add_field(name=str(map['name']), value=str(map['aliases']), inline=False)
    await Bot.send_message(msg.author, embed=emb)
    ## Part IV  ##
    emb = (discord.Embed(description="", colour=0xffa500))
    emb.set_author(name=Bot.user.name, icon_url=Bot.user.avatar_url)
    for map in maps[60:80]:
        emb.add_field(name=str(map['name']), value=str(map['aliases']), inline=False)
    await Bot.send_message(msg.author, embed=emb)
    ## Part V  ##
    emb = (discord.Embed(description="", colour=0xffa500))
    emb.set_author(name=Bot.user.name, icon_url=Bot.user.avatar_url)
    for map in maps[80:100]:
        emb.add_field(name=str(map['name']), value=str(map['aliases']), inline=False)
    await Bot.send_message(msg.author, embed=emb)
    ## Part VI ##
    emb = (discord.Embed(description="", colour=0xffa500))
    emb.set_author(name=Bot.user.name, icon_url=Bot.user.avatar_url)
    for map in maps[100:]:
        emb.add_field(name=str(map['name']), value=str(map['aliases']), inline=False)
    await Bot.send_message(msg.author, embed=emb)


# Check to see if the map nominated is an alias
async def mapname_is_valid(mpname):
    # access the global vars
    global database
    # check in name
    cursor = database.maps.find({"$or": [{'name': mpname}, {'name': "ff_" + mpname}, {"aliases": mpname}]})
    for map in cursor:
        return map['name']
    # did not find mapname
    return "INVALID"


# wait until the game starter makes a decision
async def pick_captains(caps, context):
    global BLUE_TEAM, cmdprefix, PLAYERS, RED_TEAM, sizeOfTeams, STARTER
    bcap = Bot.user.name
    rcap = Bot.user.name
    # set presence
    await Bot.change_presence(game=discord.Game(name='Selecting Captains'))

    # human readable Usage message to channel
    emb = (discord.Embed(description=STARTER[0].mention + " please select one of the options below", colour=0xffa500))
    emb.set_author(name=Bot.user.name, icon_url=Bot.user.avatar_url)
    emb.add_field(name=cmdprefix + 'captains', value='to manually select the captains', inline=False)
    emb.add_field(name=cmdprefix + 'manual', value='to manually select both teams', inline=False)
    emb.add_field(name=cmdprefix + 'shuffle', value='to randomize the captains', inline=False)
    emb.add_field(name=cmdprefix + 'random', value='to randomize the teams', inline=False)
    await Bot.send_message(context.message.channel, embed=emb)

    # check function for advance filtering
    def check(msg):
        if (msg.content.startswith(cmdprefix + 'captains')):
            return True
        elif (msg.content.startswith(cmdprefix + 'manual')):
            return True
        elif (msg.content.startswith(cmdprefix + 'shuffle')):
            return True
        elif (msg.content.startswith(cmdprefix + 'random')):
            return True
        return False

    # wait up to two (2) minutes for the game starter to make a decision
    inputobj = await Bot.wait_for_message(timeout=120, author=STARTER[0], check=check)

    # wait_for_message returns 'None' if asyncio.TimeoutError thrown
    if (inputobj != None):
        # switch on choice
        if (inputobj.content.startswith(cmdprefix + "captains")):
            # msg.mentions returns an unordered list
            # therfor we have to get each name individually
            # this way the admin has control over who is blue and red
            plyrStr = '\n'.join([p.mention for p in PLAYERS])
            await send_emb_message_to_channel_blue(STARTER[0].mention + " pick the blue team captain using @playername in your reply. Available players are:\n\n" + plyrStr, context)
            while bcap == Bot.user.name:
                try:
                    # try to get the user the admin has specified
                    inputobj = await Bot.wait_for_message(timeout=60, author=STARTER[0])
                    if (inputobj != None):
                        bcap = inputobj.mentions[0]
                        if (bcap not in PLAYERS):
                            await send_emb_message_to_channel(0xff0000, STARTER[0].mention + " player must be added to the pickup. Available players are:\n\n" + plyrStr, context)
                            bcap = Bot.user.name
                    else:  # timeout
                        await send_emb_message_to_channel_blue(STARTER[0].mention + " pick the blue team captain using @playername in your reply. Available players are:\n\n" + plyrStr, context)
                except(IndexError):
                    # keep trying if they did not mention someone
                    await send_emb_message_to_channel_blue(STARTER[0].mention + " pick the blue team captain using @playername in your reply. Available players are:\n\n" + plyrStr, context)
            # do the same for red team
            temp = []  # list for players
            for p in PLAYERS:
                if p != bcap:
                    temp.append(p)
            plyrStr = '\n'.join([p.mention for p in temp])
            await send_emb_message_to_channel_red(STARTER[0].mention + " pick the red team captain using @playername in your reply. Available players are:\n\n" + plyrStr, context)
            while rcap == Bot.user.name:
                try:
                    # try to get the user the admin has specified
                    inputobj = await Bot.wait_for_message(timeout=60, author=STARTER[0])
                    if (inputobj != None):
                        rcap = inputobj.mentions[0]
                        if (rcap not in PLAYERS):
                            await send_emb_message_to_channel(0xff0000, STARTER[0].mention + " player must be added to the pickup. Available players are:\n\n" + plyrStr, context)
                            rcap = Bot.user.name
                    else:  # timeout
                        await send_emb_message_to_channel_red(STARTER[0].mention + " pick the red team captain using @playername in your reply. Available players are:\n\n" + plyrStr, context)
                except(IndexError):
                    # keep trying if they did not mention someone
                    await send_emb_message_to_channel_red(STARTER[0].mention + " pick the red team captain using @playername in your reply. Available players are:\n\n" + plyrStr, context)
            if (bcap == rcap):
                await send_emb_message_to_channel(0xff0000, STARTER[0].mention + " you cannot pick the same captain for both teams", context)
                return False
            else:
                caps.append(bcap)
                caps.append(rcap)
                return False
        if (inputobj.content.startswith(cmdprefix + "manual")):
            plyrStr = ""
            # do the picking here so that teams are full before we leave this function
            while len(BLUE_TEAM) != sizeOfTeams:
                plyrStr = ""
                for p in PLAYERS:
                    if p not in BLUE_TEAM:
                        plyrStr += p.mention
                        plyrStr += "\n"
                await send_emb_message_to_channel_blue( STARTER[0].mention + " pick the players for the blue team using " + cmdprefix + "blue <@playername>, <@playername>, ... , <@playername> in your reply.\n\nAvailable players are:\n\n" + plyrStr + "\n\n**Current players** are: " + '\n'.join([p.mention for p in BLUE_TEAM]), context)

                # check function for advance filtering
                def check(msg):
                    return msg.content.startswith(cmdprefix + 'blue ')

                # try to get the users the admin has specified
                inputobj = await Bot.wait_for_message(timeout=60, author=STARTER[0], check=check)
                if (inputobj != None):
                    for p in inputobj.mentions:
                        if (p not in PLAYERS):
                            await send_emb_message_to_channel(0xff0000, p.mention + " is not added to the pickup." + STARTER[0].mention + " you will need to pick someone else", context)
                        else:
                            BLUE_TEAM.append(p)
                    if len(BLUE_TEAM) < sizeOfTeams:
                        # not enough players in blueTeam
                        await send_emb_message_to_channel(0xff0000, STARTER[0].mention + " this team is not full, you will need to pick " + (sizeOfTeams - len(BLUE_TEAM)) + " more players", context)
                    elif len(BLUE_TEAM) > sizeOfTeams:
                        # too many players in blueTeam
                        # loop until we have the right number
                        while len(BLUE_TEAM) != sizeOfTeams:
                            if len(BLUE_TEAM) < sizeOfTeams:
                                # admin took too many players off
                                # break and let outter loop handle this case
                                break
                            await send_emb_message_to_channel(0xff0000, STARTER[0].mention + " this team has too many players. Pick player(s) to take off using " + cmdprefix + "takeoff <@playername>, <@playername>, ... , <@playername>\n\nCurrent players are:\n\n" + '\n'.join([p.mention for p in BLUE_TEAM]), context)
                            # loop until the admin has specified someone
                            didRemove = False
                            while not didRemove:
                                # check for advanced filtering
                                def check(msg):
                                    return msg.content.startswith(cmdprefix + 'takeoff')

                                inputobj = await Bot.wait_for_message(timeout=60, author=STARTER[0], check=check)
                                if (inputobj != None):
                                    for p in inputobj.mentions:
                                        xtra = p
                                        if (xtra not in BLUE_TEAM):
                                            await send_emb_message_to_channel(0xff0000, STARTER[0].mention + " that player is not on the team you will need to pick someone else", context)
                                        else:
                                            # remove this player
                                            BLUE_TEAM.remove(xtra)
                                            didRemove = True
                                else:  # timeout
                                    await send_emb_message_to_channel(0xff0000, STARTER[0].mention + " pick the extra player to take off using " + cmdprefix + "takeoff @playername in your reply. Current players are:\n\n" + '\n'.join([p.mention for p in BLUE_TEAM]), context)
                else:  # timeout means the admin never replied correctly -> check()
                    await send_emb_message_to_channel_blue(adminRoleMention + " please " + cmdprefix + "transfer if the game starter is missing", context)
            # blueTeam is full
            # everyone else goes into the redTeam
            for p in PLAYERS:
                if p not in BLUE_TEAM:
                    RED_TEAM.append(p)
            if len(RED_TEAM) < sizeOfTeams:
                # this should never happen, but just in case
                await send_emb_message_to_channel(0xff0000, "The teams are not even " + STARTER[0].mention + " we need to do this again", context)
                return False
            else:
                # Success, so we need to setup captains to break out of outter loop
                caps.append(BLUE_TEAM[0])
                caps.append(RED_TEAM[0])
                return False
        elif (inputobj.content.startswith(cmdprefix + "shuffle")):
            if (len(PLAYERS) >= 2):
                caps.append(PLAYERS[0])
                caps.append(PLAYERS[1])
            else:
                # not enough players
                caps.append(STARTER[0])
                caps.append(STARTER[0])
            return False
        elif (inputobj.content.startswith(cmdprefix + "random")):
            if (len(PLAYERS) >= 2):
                caps.append(PLAYERS[0])
                caps.append(PLAYERS[1])
            else:
                # not enough players
                caps.append(STARTER[0])
                caps.append(STARTER[0])
            return True
        else:
            return False  # not a valid option
    else:  # inputobj == None
        return False  # timeout


async def pick_map(context):
    global CHOSEN_MAP, durationOfMapVote, LAST_MAP, MAP_PICKS, PLAYERS, poolRole, poolRoleID, sizeOfGame, sizeOfMapPool, VOTE_FOR_MAPS
    # vote for maps or random
    if (VOTE_FOR_MAPS):
        votelist = {}
        keys = []
        for k, v in MAP_PICKS.items():
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
        await send_emb_message_to_channel(0x00ff00, "Map voting has started\n\n" + poolRole.mention + " you have " + str(durationOfMapVote) + " seconds to vote for a map\n\nreply with a number between 1 and " + str(sizeOfMapPool) + " to cast your vote", context)
        await count_votes_message_channel(td, keys, context, votelist, votetotals)
        while td.total_seconds() < durationOfMapVote and len(PLAYERS) == sizeOfGame:
            async def gatherVotes(msg):
                # check function for advance filtering
                def check(msg):
                    # only accept votes from members in the pool
                    # update the vote if they change it
                    if poolRoleID in [r.id for r in msg.author.roles]:
                        for x in range(1, sizeOfMapPool + 1):
                            if msg.content == str(x):
                                votelist.update({msg.author.name: x})
                        return True

                # listen for votes, wait no more than 5 seconds between messages
                # this forces the counter to increment more often (read: more messages to the channel)
                await Bot.wait_for_message(timeout=5, check=check)

            try:
                await gatherVotes(context.message)
            except:
                pass # to keep the vote going, we want to ignore any exceptions gatherVotes() may have thrown
            elapsedtime = time.time() - countdown
            td = timedelta(seconds=elapsedtime)
            # message everyone the maps votes on every even iteration
            if (counter % 2) == 1 and (td.total_seconds() < durationOfMapVote):
                await count_votes_message_channel(td, keys, context, votelist, votetotals)
            counter += 1

        # vote time has expired
        await send_emb_message_to_channel(0xff0000, "Map voting has finished", context)

        # if users have voted
        if (len(votetotals) > 0):
            # tally up the votes
            for k, v in votelist.items():
                votetotals[v - 1] += 1

            # find the max number and it's position
            for pos, vote in enumerate(votetotals):
                if (topvote < vote):
                    topvote = vote
                    position = pos

            # now that we have the max and it's position
            # loop one final time to gather positions of duplicates
            for pos, vote in enumerate(votetotals):
                if (topvote != vote): continue  # keep looping if they are different
                # topvote == vote therefor we have a tie
                if (not duplicateFnd): duplicateFnd = True
                positions.append(pos)
        else:
            duplicateFnd = True
            positions = list(range(1, sizeOfMapPool))

        # randomly pick from list if we have a tie
        if (duplicateFnd):
            position = choice(positions)
        CHOSEN_MAP = list(MAP_PICKS.values())[position]
    else:  # random map mode
        selector, CHOSEN_MAP = choice(list(MAP_PICKS.items()))
    # tell the users what map won
    emb = (discord.Embed(title="The map has been selected", colour=0x00ff00))
    emb.set_author(name=Bot.user.name, icon_url=Bot.user.avatar_url)
    emb.add_field(name='Map', value=str(CHOSEN_MAP))  # Display the map information
    await Bot.send_message(context.message.channel, embed=emb)

    LAST_MAP = CHOSEN_MAP # set for _last()


async def pickup_is_full(context):
    global cmdprefix, PLAYERS, sizeOfGame
    if (len(PLAYERS) < sizeOfGame):
        # not full
        await send_emb_message_to_channel(0xff0000, "ABORTING: The pickup is no longer full", context)
        await Bot.change_presence(game=discord.Game(name='Pickup (' + str(len(PLAYERS)) + '/' + str(sizeOfGame) + ') ' + cmdprefix + 'add'))
        return False
    return True


# return the status of PICKUP_RUNNING
async def pickup_is_running(context):
    global PICKUP_RUNNING
    if PICKUP_RUNNING:
        return True
    else:
        await send_emb_message_to_channel(0xff0000, context.message.author.mention + " you cannot use this command, there is no pickup running right now. Use " + adminRoleMention + " to request an admin start one for you", context)
        return False


# Select the RED_TEAM
async def red_team_picks(caps, context, playerPool):
    global BLUE_TEAM, RED_TEAM, PLAYERS, server
    playerPicked = False
    await send_emb_message_to_channel(0x00ff00, caps[1].mention + " type @player to pick. Available players are:\n\n" + '\n'.join([p.mention for p in playerPool]), context)

    while not playerPicked:
        # check for a pick and catch it if they don't mention an available player
        try:
            inputobj = await Bot.wait_for_message(author=server.get_member(caps[1].id))
            picked = inputobj.mentions[0]

            # If the player is in players and they are not already picked, add to the team
            if (picked in PLAYERS):
                if (picked not in RED_TEAM and picked not in BLUE_TEAM):
                    RED_TEAM.append(picked)
                    playerPool.remove(picked)
                    playerPicked = True
                    await send_emb_message_to_channel_red(picked.mention + " has been added to the team", context)
                else:
                    await send_emb_message_to_channel(0xff0000, picked.mention + " is already on a team", context)
            else:
                await send_emb_message_to_channel(0xff0000, picked.mention + " is not in this pickup", context)
        except(IndexError):
            pass


# remove the poolRoleID from all the players from the last pickup
async def remove_everyone_from_pool_role(context):
    global BLUE_TEAM, poolRole, RED_TEAM
    # remove from all users in both teams
    for p in BLUE_TEAM:
        await Bot.remove_roles(p, poolRole)
        for p in RED_TEAM:
            await Bot.remove_roles(p, poolRole)
    # reset presence to nothing
    await Bot.change_presence(game=discord.Game(name=''))


# update MongoDB with last game information
async def save_last_game_info():
    global BLUE_TEAM, database, LAST_BLUE_TEAM, LAST_TIME, LAST_MAP, LAST_RED_TEAM, RED_TEAM
    LAST_BLUE_TEAM, LAST_RED_TEAM = [], [] # clear
    [LAST_BLUE_TEAM.append(p.name) for p in BLUE_TEAM]
    [LAST_RED_TEAM.append(p.name) for p in RED_TEAM]
    LAST_TIME = time.time()

    # modify the MongoDB document to contain the most recent pickup information
    updated = database.pickups.update_one({'last': True}, {'$set': {'blueteam': LAST_BLUE_TEAM, 'redteam': LAST_RED_TEAM, 'map': LAST_MAP, 'time': LAST_TIME}})


# Send a rich embeded messages instead of a plain ones
# to an entire channel
async def send_emb_message_to_channel(colour, embstr, context):
    emb = (discord.Embed(description=embstr, colour=colour))
    emb.set_author(name=Bot.user.name, icon_url=Bot.user.avatar_url)
    await Bot.send_message(context.message.channel, embed=emb)


# Send a rich embeded messages instead of a plain ones
# to an entire channel - Blue Team Logo
async def send_emb_message_to_channel_blue(embstr, context):
    emb = (discord.Embed(description=embstr, colour=0x0000ff))
    emb.set_author(name='Blue Team', icon_url='http://www.lexicondesigns.com/images/other/ff_logo_blue.png')
    await Bot.send_message(context.message.channel, embed=emb)


# Send a rich embeded messages instead of a plain ones
# to an entire channel - Red Team Logo
async def send_emb_message_to_channel_red(embstr, context):
    emb = (discord.Embed(description=embstr, colour=0xff0000))
    emb.set_author(name='Red Team', icon_url='http://www.lexicondesigns.com/images/other/ff_logo_red.png')
    await Bot.send_message(context.message.channel, embed=emb)


# Send a rich embeded messages instead of a plain ones
# to an individual user
async def send_emb_message_to_user(colour, embstr, context):
    emb = (discord.Embed(description=embstr, colour=colour))
    emb.set_author(name=Bot.user.name, icon_url=Bot.user.avatar_url)
    await Bot.send_message(context.message.author, embed=emb)


# send the server information to all of the players in a direct message
# send pickup game information to the channel
async def send_information(context):
    global BLUE_TEAM, CHOSEN_MAP, RED_TEAM, serverID, serverPW
    # set bot presence
    await Bot.change_presence(game=discord.Game(name='GLHF'))

    # send each user the server and password information
    redTeamMention = []
    blueTeamMention = []
    emb = (discord.Embed(title="steam://connect/" + serverID + "/" + serverPW, colour=0x00ff00))
    emb.set_author(name=Bot.user.name, icon_url=Bot.user.avatar_url)
    # try to message players server info
    # not all players allow messages
    # so pass that exception to get to everyone
    for p in RED_TEAM:
        try:
            await Bot.send_message(p, embed=emb)
        except Exception:
            pass
        redTeamMention.append(p.mention)  # so we can mention all the members of the red team
    for p in BLUE_TEAM:
        try:
            await Bot.send_message(p, embed=emb)
        except Exception:
            pass
        blueTeamMention.append(p.mention)  # so we can mention all the members of the blue team

    # Display the game information
    emb = (discord.Embed(title="The pickup is starting!!\nMap: " + CHOSEN_MAP, colour=0x00ff00))
    emb.set_author(name=Bot.user.name, icon_url=Bot.user.avatar_url)
    await Bot.send_message(context.message.channel, embed=emb)
    await send_emb_message_to_channel_blue("\n".join(map(str, blueTeamMention)), context)  # Blue Team information
    await send_emb_message_to_channel_red("\n".join(map(str, redTeamMention)), context)  # Red Team information


# create the MongoDB client and connect to the database
async def set_database():
    global database, dbclient
    dbclient = pymongo.MongoClient(dbtoken)
    database = dbclient.FortressForever


# Cycle through a user's roles to determine if they have admin access
# @returns True if they have access
async def user_has_access(author):
    if adminRoleID in [r.id for r in author.roles]: return True
    return False


async def verify_chosen_map_is_good(context):
    global CHOSEN_MAP, cmdprefix, durationOfCheckin, MAP_PICKS, STARTER
    didChoose = False
    await send_emb_message_to_channel(0xffa500, STARTER[0].mention + " the map is currently set to: " + CHOSEN_MAP[0] + "\nReply with " + cmdprefix + "accept - to **accept** the map or " + cmdprefix + "repick - to discard the map and all nominations and **repick**", context)
    while not didChoose:
        # check for advanced filtering
        def check(msg):
            if (msg.content.startswith(cmdprefix + 'accept') or msg.content.startswith(cmdprefix + 'repick')): return True
            return False

        inputobj = await Bot.wait_for_message(timeout=durationOfCheckin, author=STARTER[0], check=check)
        # wait_for_message returns 'None' if asyncio.TimeoutError thrown
        if (inputobj != None):
            didChoose = True
            # clear out CHOSEN_MAP and MAP_PICKS if admin wishes to repick
            if (inputobj.content.startswith(cmdprefix + "repick")):
                CHOSEN_MAP = []
                MAP_PICKS = {}
        else:
            didChoose = False
            await send_emb_message_to_channel(0xff0000, STARTER[0].mention + " please make a selection:\n\n" + cmdprefix + "accept to **accept** the map\n\n" + cmdprefix + "repick to discard the map and all nominations and **repick**\n\n" + CHOSEN_MAP[0], context)


#
# Bot.commands - cmdprefix + help for ingame help
#


# Add
@Bot.command(name='add', description="Add yourself to the list of players for the current pickup", brief="Add to the pickup", aliases=['add_me', 'addme', 'join'], pass_context=True)
async def _add(context):
    global CHOSEN_MAP, MAP_PICKS, PICKUP_RUNNING, PLAYERS, poolRole, sizeOfGame, STARTER, VOTE_FOR_MAPS
    if await command_is_in_wrong_channel(context): return  # To avoid cluttering and confusion, the Bot only listens to one channel
    if not await pickup_is_running(context): return  # there must be an active pickup
    # one can only add if:
    # 	they are not already added
    # 	we are not already selecting teams
    if (context.message.author in PLAYERS):
        await send_emb_message_to_channel(0xff0000, context.message.author.mention + " you have already added to this pickup", context)
        return
    elif (len(PLAYERS) == sizeOfGame):
        await send_emb_message_to_channel(0xff0000, context.message.author.mention + " sorry, the game is currently full\nYou will have to wait until the next one starts", context)
        return
    else:  # all clear to add them
        # add to pool for easier notification
        try:
            await Bot.add_roles(context.message.author, poolRole)
        except (discord.Forbidden, discord.HTTPException):
            pass
        PLAYERS.append(context.message.author)
        await send_emb_message_to_channel(0x00ff00, context.message.author.mention + " you have been added to the pickup.\nThere are currently " + str(len(PLAYERS)) + "/" + str(sizeOfGame) + " Players in the pickup", context)
        await Bot.change_presence(game=discord.Game(name='Pickup (' + str(len(PLAYERS)) + '/' + str(sizeOfGame) + ') ' + cmdprefix + 'add'))

    # each time someone adds, we need to check to see if the pickup is full
    if (len(PLAYERS) == sizeOfGame):
        # start the pickup
        reset = await go_go_gadget_pickup(context)
        if (reset):
            # Reset so we can play another one
            CHOSEN_MAP = []
            MAP_PICKS = {}
            PLAYERS = []
            STARTER = []
            PICKUP_RUNNING = False
            VOTE_FOR_MAPS = True


# Add Alias
@Bot.command(name='add_alias', description="Adds a new alias to an existing map (row) to the maps collection (table) in the MongoDB", brief="Add a new map alias", aliases=['update_map', 'updatemap'], pass_context=True)
async def _addalias(context):
    global database, server
    if await command_is_in_wrong_channel(context): return  # To avoid cluttering and confusion, the Bot only listens to one channel
    # have to manually get these for the Admin Only PM commands
    member = server.get_member(context.message.author.id)
    # admin command
    if not await user_has_access(member):
        message = context.message.content.split()
        if (len(message) > 2):
            mpname = message[1]
            # get the new alaises
            aliases = []
            for alias in message[2:]:
                aliases.append(alias)
            # first need to get the existing map and all of it's fields
            updated = database.maps.find_one_and_update(filter={}, query={"$or": [{'name': mpname}, {'name': "ff_" + mpname}, {"aliases": mpname}]},
                                                                        update={"$addToSet": {'aliases': {"$each": aliases}}},
                                                                        return_document=ReturnDocument.AFTER)
            if (updated):
                await send_emb_message_to_user(0x00ff00, "Map has been updated in the database\n\n" + str(updated['name']) + "\n\nAliases: " + str(updated['aliases']), context)
            else:
                await send_emb_message_to_user(0xff0000, "That map does not exist in the database. Did you mean to " + cmdprefix + "addmap?", context)
        else:
            await send_emb_message_to_user(0xff0000, context.message.author.mention + "\n\nThat is not how you use this command, use:\n\n" + cmdprefix + "addalias (" + cmdprefix + "updatemap) mapname_or_aliais **newalias1** **newalias2** ... **newalias#**\n\nPlease try again", context)
    else:
        await send_emb_message_to_channel(0xff0000, context.message.author.mention + " you do not have access to this command", context)


# Add Map
@Bot.command(name='addmap', description="Adds a new map (row) to the maps collection (table) in the MongoDB", brief="Add a new map", aliases=['add_map', 'new_map', 'newmap'], pass_context=True)
async def _addmap(context):
    global database, server
    if await command_is_in_wrong_channel(context): return  # To avoid cluttering and confusion, the Bot only listens to one channel
    # have to manually get these for the Admin Only PM commands
    member = server.get_member(context.message.author.id)
    # admin command
    if (await user_has_access(member)):
        message = context.message.content.split()
        if (len(message) > 1):
            # add the new map the MongoDB
            name = message[1]
            aliases = []
            for alias in message[2:]:
                aliases.append(alias)
            cursor = database.maps.find({'name': name})
            if cursor.count() == 0:
                # Mongo uses documents (key:value pairs) to represent rows of data
                database.maps.insert([{'name': name, 'aliases': aliases}])

                # verify we have done this correctly
                last = database.maps.find_one({'name': name})

                await send_emb_message_to_user(0x00ff00, "New map has been added to the database\n\n" + str(last), context)
            else:
                await send_emb_message_to_user(0xff0000, "That map already exists in the database. Did you mean to " + cmdprefix + "updatemap?", context)
        else:
            await send_emb_message_to_user(0xff0000, context.message.author.mention + "\n\nThat is not how you use this command, use:\n\n" + cmdprefix + "addmap <name> <alias1> <alias2> ... <alias##>\n\nPlease try again", context)
    else:
        await send_emb_message_to_channel(0xff0000, context.message.author.mention + " you do not have access to this command", context)


# Add Server
@Bot.command(name='addserver', description="Adds a new server (row) to the servers collection (table) in the MongoDB", brief="Add a new server", aliases=['add_server', 'new_server', 'newserver'], pass_context=True)
async def _addserver(context):
    global database, server
    if await command_is_in_wrong_channel(context): return  # To avoid cluttering and confusion, the Bot only listens to one channel
    # have to manually get these for the Admin Only PM commands
    member = server.get_member(context.message.author.id)
    # admin command
    if (await user_has_access(member)):
        message = context.message.content.split()
        if (len(message) > 4):
            # add the new server the MongoDB
            name = message[1]
            passwd = message[2]
            rcon = message[3]
            if(re.match(serverIDRegEx, message[4])):
                serverid = message[4]

                # Mongo uses documents (key:value pairs) to represent rows of data
                database.servers.insert([{'names': [name], 'passwd': passwd, 'rcon': rcon, 'serverid': serverid}])

                # verify we have done this correctly
                last = database.servers.find_one({'names': name})

                await send_emb_message_to_user(0x00ff00, "New server has been added to the database\n\n" + str(last), context)
            else:
                await send_emb_message_to_user(0xff0000, context.message.author.mention + "\n\nThat is not a valid server id, use:\n\n" + cmdprefix + "addserver <name> <password> <rcon_password> <###.###.###.###:27015>\n\nPlease try again", context)
        else:
            await send_emb_message_to_user(0xff0000, context.message.author.mention + "\n\nThat is not how you use this command, use:\n\n" + cmdprefix + "addserver <name> <password> <rcon_password> <###.###.###.###:27015>\n\nPlease try again", context)
    else:
        await send_emb_message_to_channel(0xff0000, context.message.author.mention + " you do not have access to this command", context)


# Admin
@Bot.command(name='admin', description="Displays the admin who is in control of the current pickup", brief="Displays the admin of the current pickup", aliases=['game_admin', 'gameadmin', 'game_starter', 'gamestarter', 'starter'], pass_context=True)
async def _admin(context):
    global STARTER
    if await command_is_in_wrong_channel(context): return  # To avoid cluttering and confusion, the Bot only listens to one channel
    if not await pickup_is_running(context):
        return # there must be an active pickup
    else:
        await send_emb_message_to_channel(0x00ff00, "Game Admin is: " + STARTER[0].mention, context)


# Ban
@Bot.command(name='ban', description="Admin only command that bans a user from the channel for the period specified\n\n" + cmdprefix + "ban @user length hours|days|months (pick one) Reason for the ban", brief="Ban a player", aliases=['ban_player', 'banplayer', 'timeout'], pass_context=True)
async def _ban(context):
    global database, accessRole, MAP_PICKS, PLAYERS, poolRole, timeoutRole
    if await command_is_in_wrong_channel(context): return  # To avoid cluttering and confusion, the Bot only listens to one channel
    # admin command
    if (await user_has_access(context.message.author)):
        message = context.message.content.split()
        if (len(message) > 4):
            try:
                banned = context.message.mentions[0]
                if re.match('^[0-9]*$', message[2]):
                    length = message[2]
                    origin = time.time()
                    resolution = message[3]

                    if resolution == 'hours':
                        length = int(length) * 3600
                    elif resolution == 'days':
                        length = int(length) * 86400
                    elif resolution == 'months':
                        length = int(length) * 2629740
                    else:
                        await send_emb_message_to_channel(0x00ff00, str(resolution) + " is not a valid resolution, it must be either: hours, days, or months. Please try again\n\n" + cmdprefix + "ban @user length hours|days|months (pick one) Reason for the ban", context)
                        return

                    reason = " ".join(message[4:])

                    # remove access to the channel
                    try:
                        await Bot.add_roles(banned, timeoutRole)
                        await asyncio.sleep(2)
                        await Bot.remove_roles(banned, accessRole)
                    except (discord.Forbidden, discord.HTTPException):
                        pass

                    # remove them if they are added
                    if (banned in PLAYERS):
                        PLAYERS.remove(banned)  # remove from players list
                        MAP_PICKS.pop(banned, None)  # remove this players nomination if they had one
                        try:
                            await Bot.remove_roles(banned, poolRole)
                        except Exception:
                            pass

                    # Add this ban to the MongoDB
                    query = database.banned.insert({'userid': banned.id, 'length': length, 'origin': origin, 'reason': reason})

                    print("LOG MESSAGE: " + context.message.author.name + " banned Player: " + str(banned) + " - At time " + time.strftime('%Y-%m-%d %H:%M:%S', time.localtime()) + " - for a period of " + str(message[2]) + " " + str(message[3]) + "\nReason given: " + reason)
                    await send_emb_message_to_channel(0x00ff00, banned.mention + " has been banned by " + context.message.author.mention + " (Admin)\n\nNOTE: This action has been logged", context)
                    # notify the user
                    emb = (discord.Embed(description="You have been banned by an Admin for a period of " + str(message[2]) + " " + str(message[3]) + "\nReason: " + reason, colour=0x00ff00))
                    emb.set_author(name=Bot.user.name, icon_url=Bot.user.avatar_url)
                    await Bot.send_message(banned, embed=emb)
                else:
                    await send_emb_message_to_channel(0x00ff00, "\"" + str(message[2]) + "\" is not a valid length, it must be a number. Please try again\n\n" + cmdprefix + "ban @user length hours|days|months (pick one) Reason for the ban", context)
            except (IndexError):
                await send_emb_message_to_channel(0x00ff00, "You must @mention the user, please try again\n\n" + cmdprefix + "ban @user length hours|days|months (pick one) Reason for the ban", context)
        else:
            await send_emb_message_to_channel(0xff0000, context.message.author.mention + "\n\nThat is not how you use this command, use:\n\n" + cmdprefix + "ban @user length hours|days|months (pick one) Reason for the ban\n\nPlease try again", context)
    else:
        await send_emb_message_to_channel(0xff0000, context.message.author.mention + " you do not have access to this command", context)


# Bitcoin
@Bot.command(name='bitcoin', description="Get the current price of bitcoin in USD", brief="Convert BTC to USD", aliases=['btc'])
async def _bitcoin():
    url = 'https://api.coindesk.com/v1/bpi/currentprice/BTC.json'
    response = requests.get(url)
    value = response.json()['bpi']['USD']['rate']
    await Bot.say("Bitcoin price is currently: $" + value)


# Changelevel
@Bot.command(name='changelevel', description="Change the map in the server using the RCON commange changelevel", brief="Change the map in serever", aliases=['changemap', 'rcon changemap', 'rcon_changemap', 'rcon changelevel', 'rcon_changelevel'], pass_context=True)
async def _changelevel(context):
    global rcon
    if await command_is_in_wrong_channel(context): return  # To avoid cluttering and confusion, the Bot only listens to one channel
    # admin command
    if (await user_has_access(context.message.author)):
        message = context.message.content.split()
        # make sure the user provided a map
        if (len(message) > 1):
            # check to see if the provided map is in the database
            atom = await mapname_is_valid(message[1])
            if (atom != "INVALID"):
                # change the map in the server to the provided map
                try:
                    rcon.execute('changelevel ' + atom)
                except Exception:
                    pass
                await send_emb_message_to_channel(0x00ff00, context.message.author.mention + " the map has been changed to " + atom, context)
            else:
                await send_emb_message_to_channel(0xff0000, context.message.author.mention + " that map is not in my " + cmdprefix + "maplist. Please make another selection", context)
                await list_all_the_maps(context.message)
        else:
            await send_emb_message_to_channel(0xff0000, context.message.author.mention + " you must provide a mapname. " + cmdprefix + "changemap mapname", context)
    else:
        await send_emb_message_to_channel(0xff0000, context.message.author.mention + " you do not have access to this command", context)


# Delete Map
@Bot.command(name='delmap', description="Removes an existing map (row) from the maps collection (table) in the MongoDB", brief="Delete an existing server", aliases=['del_map', 'delete_map', 'deletemap'], pass_context=True)
async def _delmap(context):
    global database, server
    if await command_is_in_wrong_channel(context): return  # To avoid cluttering and confusion, the Bot only listens to one channel
    # have to manually get these for the Admin Only PM commands
    member = server.get_member(context.message.author.id)
    # admin command
    if (await user_has_access(member)):
        message = context.message.content.split()
        if (len(message) > 1):
            name = message[1]

            # Mongo uses documents (key:value pairs) to represent rows of data
            removed = database.maps.delete_one({'name': name})
            print("LOG MESSAGE: " + context.message.author.name + " deleted MAP: " + name + " - At time " + time.strftime('%Y-%m-%d %H:%M:%S', time.localtime()))
            await send_emb_message_to_user(0x00ff00, "Map has been removed from the database\n\n" + str(removed) + "\n\nNOTE: This action has been logged", context)
        else:
            await send_emb_message_to_user(0xff0000, context.message.author.mention + "\n\nThat is not how you use this command, use:\n\n" + cmdprefix + "delmap <name>\n\nYour entries must match exactly. Please try again", context)
    else:
        await send_emb_message_to_channel(0xff0000, context.message.author.mention + " you do not have access to this command", context)


# Delete Server - Removes an existing server (read: row) from the servers collection (read: table) in the MongoDB
@Bot.command(name='delserver', description="Removes an existing map (row) from the maps collection (table) in the MongoDB", brief="Delete an existing server", aliases=['del_server', 'delete_server', 'deleteserver'], pass_context=True)
async def _delserver(context):
    global database, server
    if await command_is_in_wrong_channel(context): return  # To avoid cluttering and confusion, the Bot only listens to one channel
    # have to manually get these for the Admin Only PM commands
    member = server.get_member(context.message.author.id)
    # admin command
    if (await user_has_access(member)):
        message = context.message.content.split()
        if (len(message) > 4):
            # add the new server the MongoDB
            name = message[1]
            passwd = message[2]
            rcon = message[3]
            if (re.match(serverIDRegEx, message[4])):
                serverid = message[4]

                query = {'names': [name], 'passwd': passwd, 'rcon': rcon, 'serverid': serverid}
                # Mongo uses documents (key:value pairs) to represent rows of data
                removed = database.servers.delete_one(query)
                print("LOG MESSAGE: " + context.message.author.name + " deleted server: " + str(query) +" - At time " + time.strftime('%Y-%m-%d %H:%M:%S', time.localtime()))
                await send_emb_message_to_user(0x00ff00, "Server has been removed from the database\n\n" + str(removed) + "\n\nNOTE: This action has been logged", context)
            else:
                await send_emb_message_to_user(0xff0000, context.message.author.mention + "\n\nThat is not a valid server id, use:\n\n" + cmdprefix + "addserver <name> <password> <rcon_password> <###.###.###.###:27015>\n\nPlease try again", context)
        else:
            await send_emb_message_to_user(0xff0000, context.message.author.mention + "\n\nThat is not how you use this command, you must do:\n\n" + cmdprefix + "delserver name password rcon_password ###.###.###.###:27015\n\nYour entries must match exactly. Please try again", context)
    else:
        await send_emb_message_to_channel(0xff0000, context.message.author.mention + " you do not have access to this command", context)


# Demos
@Bot.command(name='demos', description="Provides the message author with a link to the currently stored demos via direct message", brief="Get a link to the demos", aliases=['demo', 'recordings', 'recording'], pass_context=True)
async def _demos(context):
    await send_emb_message_to_user(0xffa500, "SourceTV demos can be found here: http://www.ffpickup.com/?p=demos", context)


# End
@Bot.command(name='end', description="Admin only command that ends the current pickup", brief="End the current pickup", aliases=['edn', 'kill', 'ned', 'stop'], pass_context=True)
async def _end(context):
    global CHOSEN_MAP, MAP_PICKS, PICKUP_RUNNING, PLAYERS, poolRole, STARTER
    if await command_is_in_wrong_channel(context): return  # To avoid cluttering and confusion, the Bot only listens to one channel
    if not await pickup_is_running(context): return  # there must be an active pickup
    # admin command
    if (await user_has_access(context.message.author)):
        # only end if admin is game_starter or game_starter does not !veto in time
        if (STARTER[0] == context.message.author or not await check_for_veto(cmdprefix + "end", context)):
            CHOSEN_MAP = []
            MAP_PICKS.clear()
            for p in PLAYERS:
                try:
                    await Bot.remove_roles(p, poolRole)
                except Exception:
                    pass
            del PLAYERS[:]
            del STARTER[:]
            PICKUP_RUNNING = False
            await send_emb_message_to_channel(0x00ff00, "The pickup has been ended by an admin", context)
            await Bot.change_presence(game=discord.Game(name=' '))
        else:
            await send_emb_message_to_channel(0xff0000, STARTER[0].mention + " has vetoed the command", context)
    else:
        await send_emb_message_to_channel(0xff0000, context.message.author.mention + " you do not have access to this command", context)


# Hawking
@Bot.command(name='hawking', description="Displays a random quote from The Great Dr. Hawking", brief="Quote from Dr. Stephen Hawking", aliases=['hawking_quote', 'hawkingquote', 'quote'], pass_context=True)
async def _hawking(context):
    quote, source = choice(list(quotes.items()))
    emb = (discord.Embed(description=quote, colour=0x5e7750))
    emb.set_author(name="Dr. Stephen William Hawking, 1942-2018", icon_url=Bot.user.avatar_url)
    emb.add_field(name='Source:', value=source, inline=False)
    await Bot.send_message(context.message.channel, embed=emb)


# Journals
@Bot.command(name='journals', description="Displays a link to 55 papers in Physical Review D and Physical Review Letters, gathered together and made public by the American Physical Society", brief="Link to Stephen Hawking journals", aliases=['aps', 'american_physical_society', 'americanphysicalsociety', 'hawking_journal','hawkingjournal', 'hawking_journals','hawkingjournals', 'journal'], pass_context=True)
async def _journals(context):
    emb = (discord.Embed(description='''To mark the passing of Stephen Hawking, the American Physical Society have gathered together and made free to read his 55 papers in the peer-reviewed, scientific journals Physical Review D and Physical Review Letters.''', colour=0x5e7750))
    emb.set_author(name="Dr. Stephen William Hawking, 1942-2018", icon_url=Bot.user.avatar_url)
    emb.add_field(name='Link:', value='https://journals.aps.org/collections/stephen-hawking', inline=False)
    await Bot.send_message(context.message.channel, embed=emb)


# Last
@Bot.command(name='last', description="Displays information about the last pickup that was played", brief="Show the last pickup info", aliases=['last_game','lastgame', 'last_pug', 'lastpug'], pass_context=True)
async def _last(context):
    global database, dbclient, LAST_BLUE_TEAM, LAST_TIME, LAST_MAP, LAST_RED_TEAM
    if await command_is_in_wrong_channel(context): return  # To avoid cluttering and confusion, the Bot only listens to one channel
    await set_database()
    found = database.pickups.find_one({'last': True})
    LAST_BLUE_TEAM = found.get('blueteam')
    LAST_RED_TEAM = found.get('redteam')
    LAST_MAP = found.get('map')
    LAST_TIME = found.get('time')

    # set up the timedelta
    elapsedtime = time.time() - LAST_TIME
    td = timedelta(seconds=elapsedtime)
    td = td - timedelta(microseconds=td.microseconds)

    # we have to send these as multiple embed messages
    # if we try to send more than 2000 characters discord raises a 400 request error
    emb = (discord.Embed(title="Last Pickup was " + str(td) + " ago on " + LAST_MAP, colour=0x00ff00))
    emb.set_author(name=Bot.user.name, icon_url=Bot.user.avatar_url)
    await Bot.send_message(context.message.channel, embed=emb)
    await send_emb_message_to_channel_blue("\n".join(map(str, LAST_BLUE_TEAM)), context)
    await send_emb_message_to_channel_red("\n".join(map(str, LAST_RED_TEAM)), context)
    # close the database
    dbclient.close()


# Map
@Bot.command(name='map', description="Show the chosen map for the current pickup", brief="Show the selected map", aliases=['what_map_won','whatmapwon'], pass_context=True)
async def _map(context):
    global CHOSEN_MAP
    if await command_is_in_wrong_channel(context): return  # To avoid cluttering and confusion, the Bot only listens to one channel
    if not await pickup_is_running(context): return     # there must be an active pickup
    # only allow if pickup selection has already begun
    if (len(CHOSEN_MAP) > 0):
        await send_emb_message_to_channel(0x00ff00, "The map for this pickup is " + CHOSEN_MAP[0], context)
    else:
        await send_emb_message_to_channel(0xff0000, context.message.author.mention + " there has not been a map pick for this pickup yet", context)


# Maps
@Bot.command(name='maps', description="List all of the maps that have been nominated for the current pickup", brief="Show the nominated maps", aliases=['nominated', 'nominate_maps','nominatedmaps'], pass_context=True)
async def _maps(context):
    global MAP_PICKS, sizeOfMapPool
    if await command_is_in_wrong_channel(context): return  # To avoid cluttering and confusion, the Bot only listens to one channel
    if not await pickup_is_running(context): return  # there must be an active pickup
    # need to build the list of maps
    mapStr = ""
    for k in MAP_PICKS:
        mapStr = mapStr + str(MAP_PICKS[k]) + " (" + k.mention + ")\n"
    await send_emb_message_to_channel(0x00ff00, "Current Maps (" + str(len(MAP_PICKS)) + "/" + str(sizeOfMapPool) + ")\n" + mapStr, context)


# Maplist
@Bot.command(name='maplist', description="Provides you with a list of all the maps that are available for nomination via direct message", brief="Show the list of maps available", aliases=['list_maps', 'listmaps','map_list'], pass_context=True)
async def _maplist(context):
    if await command_is_in_wrong_channel(context): return  # To avoid cluttering and confusion, the Bot only listens to one channel
    await list_all_the_maps(context.message)


# Nominate
@Bot.command(name='nominate', description="Nominate the map you specified, provided it is valid", brief="Nominate the specified map", aliases=['elect', 'iwanttoplay','nom'], pass_context=True)
async def _nominate(context):
    global CHOSEN_MAP, MAP_PICKS, PLAYERS, sizeOfMapPool, STARTER
    if await command_is_in_wrong_channel(context): return  # To avoid cluttering and confusion, the Bot only listens to one channel
    if not await pickup_is_running(context): return  # there must be an active pickup
    # only allow if pickup has not already begun
    if len(CHOSEN_MAP) > 0:
        await send_emb_message_to_channel(0xff0000, context.message.author.mention + " you cannot nominate maps once the map has already been chosen\nCurrent Map: " + CHOSEN_MAP[0], context)
    else:
        # must also be added to the current pickup
        if (context.message.author in PLAYERS):
            message = context.message.content.split()
            # make sure the user provided a map
            if (len(message) > 1):
                # check to see if the provided map is valid
                atom = await mapname_is_valid(message[1])
                if (atom != "INVALID"):
                    # check to see if someone else noimated this map
                    for a, mp in MAP_PICKS.items():
                        if (atom == str(mp)):
                            await send_emb_message_to_channel(0xff0000, context.message.author.mention + " that map has already been nominated. Please make another selection", context)
                            return  # break out if duplicate nomination

                    # only allow a certain number of maps
                    if (len(MAP_PICKS) < sizeOfMapPool or context.message.author in MAP_PICKS):
                        # users may only nominate one map
                        MAP_PICKS.update({context.message.author : atom})
                        await send_emb_message_to_channel(0x00ff00, context.message.author.mention + " has nominated " + atom, context)
                    else:
                        # need to build the list of maps
                        mapStr = ""
                        for k in MAP_PICKS:
                            mapStr = mapStr + str(MAP_PICKS[k]) + " (" + k.mention + ")\n"
                        emb = (discord.Embed(description=context.message.author.mention + " there is already more than " + str(sizeOfMapPool) + " maps nominated", colour=0xff0000))
                        emb.set_author(name=Bot.user.name, icon_url=Bot.user.avatar_url)
                        emb.add_field(name='Current Maps', value=mapStr, inline=False)
                        await Bot.send_message(context.message.channel, embed=emb)
                else:
                    await send_emb_message_to_channel(0xff0000, context.message.author.mention + " that map is not in my " + cmdprefix + "maplist. Please make another selection", context)
                    await list_all_the_maps(context.message)
            else:
                await send_emb_message_to_channel(0xff0000, context.message.author.mention + " that is not how you use this command, use:\n\n" + cmdprefix + "nominate mapname", context)
        else:
            await send_emb_message_to_channel(0xff0000, context.message.author.mention + " you cannot use this command, you must be added to the pickup to nominate maps", context)


# Pickup
@Bot.command(name='pickup', description="Start a new pickup, if one is not already currently running", brief="Start a new pickup", aliases=['new_game', 'newgame', 'new', 'new_pickup', 'pikcup', 'start', 'start_game'], pass_context=True)
async def _pickup(context):
    global PICKUP_RUNNING, PLAYERS, sizeOfGame, sizeOfTeams, START_TIME, STARTER
    if await command_is_in_wrong_channel(context): return  # To avoid cluttering and confusion, the Bot only listens to one channel
    # admin command
    if (await user_has_access(context.message.author)):
        # only start one if there is not already one running
        if (PICKUP_RUNNING):
            await send_emb_message_to_channel(0xff0000, "There is already a pickup running. " + cmdprefix + "teams to see the game details", context)
        else:
            PICKUP_RUNNING = True
            STARTER.clear()
            STARTER.append(context.message.author)
            sizeOfGame = config.sizeOfGame
            sizeOfTeams = config.sizeOfTeams
            await send_emb_message_to_channel(0x00ff00, "A pickup has been started. " + cmdprefix + "add to join up.", context)
            await Bot.change_presence(game=discord.Game(name='Pickup (' + str(len(PLAYERS)) + '/' + str(sizeOfGame) + ') ' + cmdprefix + 'add'))
            START_TIME = time.time()
    else:
        await send_emb_message_to_channel(0xff0000, context.message.author.mention + " you do not have access to this command", context)


# Players
@Bot.command(name='players', description="Change the number of players per team (Admin only)", brief="Change the number of players in pickup", aliases=['players_per_team', 'size_of_teams', 'sizeofteams', 'team_size', 'teamsize'], pass_context=True)
async def _players(context):
    global PLAYERS, sizeOfGame, sizeOfTeams, STARTER
    if await command_is_in_wrong_channel(context): return  # To avoid cluttering and confusion, the Bot only listens to one channel
    if not await pickup_is_running(context): return  # there must be an active pickup
    # admin command
    if (await user_has_access(context.message.author)):
        # make sure this admin owns this pickup
        if (STARTER[0] == context.message.author):
            message = context.message.content.split()
            if (len(message) >= 1):
                # make sure the msg.author is giving an integer value
                try:
                    sz = int(message[1])
                    if (sz == 0):
                        # zero players? Just end it then
                        await send_emb_message_to_channel(0xff0000, context.message.author.mention + " you cannot change to zero players, please use " + cmdprefix + "end instead", context)
                    elif ((sz % 2) == 0):
                        # even number
                        if (sz < len(PLAYERS)):
                            # do not lower sizes if more players have added already
                            await send_emb_message_to_channel(0xff0000, context.message.author.mention + " the player pool is too big to change to that value", context)
                        else:
                            sizeOfTeams = int(sz / 2)
                            sizeOfGame = int(sz)
                            await send_emb_message_to_channel(0x00ff00, context.message.author.mention + " the size of the game has been changed to " + str(sz), context)
                            await Bot.change_presence(game=discord.Game(name='Pickup (' + str(len(PLAYERS)) + '/' + str(sizeOfGame) + ') ' + cmdprefix + 'add'))
                    else: # odd number
                        await send_emb_message_to_channel(0xff0000, context.message.author.mention + " the size of the teams must be even", context)
                except(ValueError):
                    await send_emb_message_to_channel(0xff0000, context.message.author.mention + " " + message[1] + " is not a valid number. Use " + cmdprefix + "players #", context)
            else:
                await send_emb_message_to_channel(0xff0000, "You must provide a new size " + cmdprefix + "players numberOfPlayers", context)
        else:
            await send_emb_message_to_channel(0xff0000, context.message.author.mention + " sorry, this pickup does not belong to you, it belongs to " + STARTER[0].mention, context)
    else:
        await send_emb_message_to_channel(0xff0000, context.message.author.mention + " you do not have access to this command", context)


# Pug
@Bot.command(name='pug', description="Allow user access to the pickup channel ", brief="Give you access to the channel", aliases=['letmein'], pass_context=True)
async def _pug(context):
    global accessRole, requestChannelID, timeoutRoleID
    if await command_is_in_wrong_channel(context): return  # To avoid cluttering and confusion, the Bot only listens to one channel
    try:
        await Bot.add_roles(context.message.author, accessRole)
        await send_emb_message_to_channel(0x00ff00, "Successfully added role {0}".format(accessRole.name), context)
    except (discord.Forbidden, discord.HTTPException):
        pass


# Pugbot (Magic 8-Ball)
@Bot.command(name='pugbot', description="Answers a yes or no question", brief="Answers from the pugbot", aliases=['8ball', '8-ball', 'eight_ball', 'eightball'], pass_context=True)
async def _eight_ball(context):
    possible_responses = ['It is certain', 'It is decidedly so', 'Without a doubt', 'Yes - definitely', 'You may rely on it', 'As I see it, yes',
                          'Most likely', 'Outlook good', 'Yes', 'Signs point to yes', 'Reply hazy, try again', 'Ask again later', 'Better not tell you now',
                          'Cannot predict now', 'Concentrate and ask again', 'Don\'t count on it', 'My reply is no', 'My sources say no', 'Outlook not so good',
                          'Very doubtful']
    await Bot.say(choice(possible_responses) + " " + context.message.author.mention)


# Radicaldad
@Bot.command(name='radicaldad', description="", brief="Not for you", pass_context=True)
async def _radicaldad(context):
    global CHOSEN_MAP, MAP_PICKS, PICKUP_RUNNING, PLAYERS, poolRole, sizeOfGame, STARTER, vipPlayerID, VOTE_FOR_MAPS
    # same as add but with the restriction on ID
    if context.message.author.id == vipPlayerID:
        if not await pickup_is_running(context): return  # there must be an active pickup
        if (context.message.author in PLAYERS):
            await send_emb_message_to_channel(0xff0000, context.message.author.mention + " you have already added to this pickup", context)
            return
        elif (len(PLAYERS) == sizeOfGame):
            await send_emb_message_to_channel(0xff0000, context.message.author.mention + " sorry, the game is currently full\nYou will have to wait until the next one starts", context)
            return
        else:  # all clear to add them
            # add to pool for easier notification
            try:
                await Bot.add_roles(context.message.author, poolRole)
            except (discord.Forbidden, discord.HTTPException):
                pass
            PLAYERS.append(context.message.author)
            await send_emb_message_to_channel(0x00ff00, context.message.author.mention + " you have been added to the pickup.\nThere are currently " + str(len(PLAYERS)) + "/" + str(sizeOfGame) + " Players in the pickup", context)
            await Bot.change_presence(game=discord.Game(name='Pickup (' + str(len(PLAYERS)) + '/' + str(sizeOfGame) + ') ' + cmdprefix + 'add'))

        # each time someone adds, we need to check to see if the pickup is full
        if (len(PLAYERS) == sizeOfGame):
            # start the pickup
            reset = await go_go_gadget_pickup(context)
            if (reset):
                # Reset so we can play another one
                CHOSEN_MAP = []
                MAP_PICKS = {}
                PLAYERS = []
                STARTER = []
                PICKUP_RUNNING = False
                VOTE_FOR_MAPS = True


# Records
@Bot.command(name='records', description="Get a link to the All-time Records on ffpickup.com", brief="Get a link to the All-time Records", aliases=['alltime', 'alltime_records', 'best'], pass_context=True)
async def _records(context):
    await send_emb_message_to_user(0xffa500, "All-time Records (work in progress): http://parser.ffpickup.com/v2/records/", context)


# Remove
@Bot.command(name='remove', description="Remove yourself or the specified player (Admin only) and any map nomination they may have from the pickup", brief="Removes the user from the pickup", aliases=['removeme', 'remove_me', 'removeplayer', 'remove_player'], pass_context=True)
async def _remove(context):
    global MAP_PICKS, PLAYERS, poolRole, sizeOfGame
    if await command_is_in_wrong_channel(context): return  # To avoid cluttering and confusion, the Bot only listens to one channel
    if not await pickup_is_running(context): return  # there must be an active pickup
    try:
        idleUser = context.message.mentions[0]
        # must be an admin to remove someone other than yourself
        if (await user_has_access(context.message.author)):
            if (idleUser in PLAYERS):
                PLAYERS.remove(idleUser)  # remove from players list
                MAP_PICKS.pop(idleUser, None)  # remove this players nomination if they had one
                try:
                    await Bot.remove_roles(context.message.mentions[0], poolRole)
                except Exception:
                    pass
                await send_emb_message_to_channel(0x00ff00, context.message.mentions[0].mention + " you have been removed from the pickup by " + context.message.author.mention + " (admin)", context)
                await Bot.change_presence(game=discord.Game( name='Pickup (' + str(len(PLAYERS)) + '/' + str(sizeOfGame) + ') ' + cmdprefix + 'add'))
            else:
                await send_emb_message_to_channel(0x00ff00, context.message.author.mention + " that user is not added to the pickup", context)
        else:
            await send_emb_message_to_channel(0xff0000, context.message.author.mention + " you do not have access to this command", context)
    except(IndexError):
        # no user mentioned so check if the author is in pickup
        idleUser = context.message.author
        if (idleUser in PLAYERS):
            PLAYERS.remove(idleUser)  # remove from players list
            MAP_PICKS.pop(idleUser, None)  # remove this players nomination if they had one
            try:
                await Bot.remove_roles(idleUser, poolRole)
            except Exception:
                pass
            await send_emb_message_to_channel(0x00ff00, context.message.author.mention + " you have been removed from the pickup", context)
            await Bot.change_presence(game=discord.Game( name='Pickup (' + str(len(PLAYERS)) + '/' + str(sizeOfGame) + ') ' + cmdprefix + 'add'))
        else:
            await send_emb_message_to_channel(0x00ff00, context.message.author.mention + " no worries, you never even added", context)


# Remove Nomination
@Bot.command(name='removenom', description="Allows an admin to remove a map nominate from the list", brief="Removes the specified map nomination from the pickup", aliases=['removenomination', 'remove_nom', 'remove_nomination', 'vetonomination', 'veto_nom', 'veto_nomination'], pass_context=True)
async def _removenom(context):
    global MAP_PICKS
    if await command_is_in_wrong_channel(context): return  # To avoid cluttering and confusion, the Bot only listens to one channel
    if not await pickup_is_running(context): return  # there must be an active pickup
    # must be an admin to remove a map nomination
    if (await user_has_access(context.message.author)):
        message = context.message.content.split()
        # make sure the user provided a map
        if (len(message) > 1):
            # check to see if the provided map is an alias
            atom = await mapname_is_valid(message[1])
            if (atom != "INVALID"):
                # check to see if someone has noimated this map
                for author, mp in MAP_PICKS.items():
                    if (atom == str(mp)):
                        # remove this nomination
                        MAP_PICKS.pop(author, None)
                        await send_emb_message_to_channel(0x00ff00, atom + " has been removed from the nominations by " + context.message.author.mention + " (admin)", context)
                        return
                # no match found
                await send_emb_message_to_channel(0xff0000, atom + " is not a nominated map currently", context)
            else:
                await send_emb_message_to_channel(0xff0000, context.message.author.mention + " that mapname is not a valid map. Please make another selection", context)
        else:
            await send_emb_message_to_channel(0xff0000, context.message.author.mention + " you must provide a mapname. " + cmdprefix + "removenom mapname", context)
    else: # not an admin
        await send_emb_message_to_channel(0xff0000, context.message.author.mention + " you do not have access to this command", context)


# Setmode
@Bot.command(name='setmode', description="Allows an admin to change the way the map is picked. Options are random or vote", brief="Change the way the map is picked", aliases=['changemode', 'change_mode', 'set_mode'], pass_context=True)
async def _setmode(context):
    global STARTER, VOTE_FOR_MAPS
    if await command_is_in_wrong_channel(context): return  # To avoid cluttering and confusion, the Bot only listens to one channel
    if not await pickup_is_running(context): return  # there must be an active pickup
    # admin command
    if (await user_has_access(context.message.author)):
        # make sure this admin owns this pickup
        if STARTER[0] == context.message.author:
            message = context.message.content.split()
            try:
                m = message[1]
                if (m.startswith("random")):
                    VOTE_FOR_MAPS = False
                    await send_emb_message_to_channel(0x00ff00, "Map Selection has successfully been changed to randomly select from the list of nominations", context)
                elif (m.startswith("vote")):
                    VOTE_FOR_MAPS = True
                    await send_emb_message_to_channel(0x00ff00, "Map Selection has successfully been changed to call a player vote", context)
                else:
                    await send_emb_message_to_channel(0xff0000, context.message.author.mention + " that is not a valid mode you must type " + cmdprefix + "setmode random or " + cmdprefix + "setmode vote", context)
                    return
            except(IndexError):
                await send_emb_message_to_channel(0xff0000, context.message.author.mention + " to change the map selection mode you must type " + cmdprefix + "setmode random or " + cmdprefix + "setmode vote", context)
                return
        else:
            await send_emb_message_to_channel(0xff0000, context.message.author.mention + " sorry, this pickup does not belong to you, it belongs to " + STARTER[0].mention, context)
    else:
        await send_emb_message_to_channel(0xff0000, context.message.author.mention + " you do not have access to this command", context)


# Setserver
@Bot.command(name='setserver', description="Change the server the pickup will be played on (Game Starter Only)", brief="Change the server information", aliases=['changeserver', 'change_server', 'server', 'set_server'], pass_context=True)
async def _setserver(context):
    global database, server_address, serverID, serverPW, rcon, rconPW, STARTER
    if await command_is_in_wrong_channel(context): return  # To avoid cluttering and confusion, the Bot only listens to one channel
    if not await pickup_is_running(context): return  # there must be an active pickup
    # admin command
    if (await user_has_access(context.message.author)):
        # make sure this admin owns this pickup
        if (STARTER[0] == context.message.author):
            message = context.message.content.split()
            if (len(message) > 2):
                cursor = None
                # switch on flag and search the MongoDB for a document that contains that op:data
                op = message[1]
                data = message[2]
                if (op == "name"):
                    cursor = database.servers.find({'names': data})
                elif (op == "server"):
                    cursor = database.servers.find({'serverid': data})
                #TODO: Add an option to supply a server in the command
                # check for a match
                if(cursor is not None and cursor.count() > 0):
                    for doc in cursor:
                        # doc is a dict
                        serverID = doc['serverid']
                        serverPW = doc['passwd']
                        rconPW = doc['rcon']
                        server_address = (serverID[:-6], 27015)
                        # reset rcon to our new RCON connection
                        rcon = valve.rcon.RCON(server_address, rconPW)
                        rcon.connect()
                        rcon.authenticate()
                        await send_emb_message_to_user(0x00ff00, context.message.author.mention + " changing server\n\nServerID: " + serverID + "\n\nServer Address: " + str(server_address) + "\n\nPassword: " + serverPW + "\n\nRCON: " + rconPW, context)
                else:
                    await send_emb_message_to_channel(0xff0000, context.message.author.mention + " I am sorry, I did not find a server matching " + op + " = " + data + "\n\nPlease try again", context)
            else:
                await send_emb_message_to_channel(0xff0000, context.message.author.mention + "\n\nThat is not how you use this command, options are either:\n" + cmdprefix + "setserver name serverAlias\n" + cmdprefix + "server serverID " + serverPattern + "\n\nPlease try again", context)
        else:
            await send_emb_message_to_channel(0xff0000, context.message.author.mention + " sorry, this pickup does not belong to you, it belongs to " + STARTER[0].mention, context)
    else:
        await send_emb_message_to_channel(0xff0000, context.message.author.mention + " you do not have access to this command", context)


# Sendinfo
@Bot.command(name='sendinfo', description="Sends the server IP and password via direct message", brief="Send server info via DM", aliases=['send_info'], pass_context=True)
async def _sendinfo(context):
    global serverID, serverPW
    if await command_is_in_wrong_channel(context): return  # To avoid cluttering and confusion, the Bot only listens to one channel
    await send_emb_message_to_user(0x00ff00, "steam://connect/" + serverID + "/" + serverPW, context)


# Teams
@Bot.command(name='teams', description="Displays all of the members in the current pickup", brief="Display current pickup info", aliases=['game_info', 'gameinfo'], pass_context=True)
async def _teams(context):
    global PLAYERS
    if await command_is_in_wrong_channel(context): return  # To avoid cluttering and confusion, the Bot only listens to one channel
    if not await pickup_is_running(context): return  # there must be an active pickup
    if (len(PLAYERS) < 1):
        await send_emb_message_to_channel(0x00ff00, "The pickup is empty right now. " + cmdprefix + "add to join", context)
    elif (len(PLAYERS) > 0):
        plyrStr = '\n'.join([p.mention for p in PLAYERS])
        await send_emb_message_to_channel(0x00ff00, "Players:\n" + plyrStr, context)


# Transfer
@Bot.command(name='transfer', description="Give your pickup to another admin (Game Starter) or take possesion of another admins pickup (All Other Admins)", brief="Transfer the current pickup to/from another admin", aliases=['give', 'take'], pass_context=True)
async def _transfer(context):
    global STARTER
    if await command_is_in_wrong_channel(context): return  # To avoid cluttering and confusion, the Bot only listens to one channel
    if not await pickup_is_running(context): return  # there must be an active pickup
    # admin command
    if (await user_has_access(context.message.author)):
        # does this admin own this pickup
        if (STARTER[0] == context.message.author):
            # check for a pick and catch it if they didn't mention an available player
            try:
                newCap = context.message.mentions[0]
                # do not transfer your own pickup to yourself
                if newCap != STARTER[0]:
                    # verify the mentioned user is also an admin
                    if (await user_has_access(newCap)):
                        STARTER.clear()
                        STARTER.append(newCap)
                        await send_emb_message_to_channel(0x00ff00, context.message.author.mention + " your pickup has successfully been transfered to " + newCap.mention, context)
                    else:
                        await send_emb_message_to_channel(0xff0000, context.message.author.mention + " you may only transfer your pickup to another admin", context)
                else:
                    await send_emb_message_to_channel(0xff0000, context.message.author.mention + " you already own this pickup", context)
            except(IndexError):
                await send_emb_message_to_channel(0xff0000, context.message.author.mention + " you must type " + cmdprefix + "transfer @nameOfAdmin to transfer your pickup.", context)
                return  # break out if they did not specify a user
        else:  # someone who does not own pickup is trying to transfer
            try:
                # sometimes we forget who owns the pickup and try to transfer someone else's pickup
                # we can catch this by checking for a mention AFTER verifying author is not starter (done above)
                newCap = context.message.mentions[0]
                await send_emb_message_to_channel(0xff0000, context.message.author.mention + " you may only transfer your own pickup to another player", context)
                return  # break out if they accidentally specify a user
            except(IndexError):
                # they did not mention a user therefor they must be trying to take over a pickup
                if (not await check_for_veto(cmdprefix + "transfer", context)):
                    await send_emb_message_to_channel(0x00ff00, context.message.author.mention + " you have successfully taken possesion of " + STARTER[0].mention + " pickup", context)
                    STARTER.clear()
                    STARTER.append(context.message.author)
                else:
                    await send_emb_message_to_channel(0xff0000, STARTER[0].mention + " has vetoed the transfer", context)
    else:
        await send_emb_message_to_channel(0xff0000, context.message.author.mention + " you do not have access to this command", context)


# Unban
@Bot.command(name='unban', description="Remove a ban for the specifed user from the database and grant them access once more", brief="Unban a player", aliases=['del_ban', 'delban', 'un_ban', 'remove_ban', 'removeban'], pass_context=True)
async def _unban(context):
    global bannedChannelID, database, dbclient
    if await command_is_in_wrong_channel(context): return  # To avoid cluttering and confusion, the Bot only listens to one channel
    # admin command
    if (await user_has_access(context.message.author)):
        try:
            banned = context.message.mentions[0]
            message = context.message.content.split()
            if len(message) >= 3:
                await set_database()
                reason = " ".join(message[2:])

                # delete the ban from the MongoDB
                database.banned.delete_one({'userid': banned.id})

                # give user back access
                member = server.get_member(banned.id)
                try:
                    await Bot.remove_roles(member, timeoutRole)
                    await asyncio.sleep(2)
                    await Bot.add_roles(member, accessRole)
                except Exception:
                    pass

                # notify the admins
                emb = (discord.Embed(description="The ban for user " + member.mention + " has been removed by " + context.message.author.mention + " (Admin)\nReason given: " + reason + "\n\nNOTE: This action has been logged", colour=0x00ff00))
                emb.set_author(name=Bot.user.name, icon_url=Bot.user.avatar_url)
                await Bot.send_message(server.get_channel(bannedChannelID), embed=emb)
                # notify the user
                emb = (discord.Embed(description="Your ban has been removed by " + context.message.author.mention + " (Admin)\nReason given: " + reason + "\n\nNOTE: This action has been logged", colour=0x00ff00))
                emb.set_author(name=Bot.user.name, icon_url=Bot.user.avatar_url)
                await Bot.send_message(member, embed=emb)
                print("LOG MESSAGE: The ban for Player: " + str(member) + " has been removed by " + context.message.author.name + " (Admin) for reason: " + reason)
                dbclient.close()
            else:
                await send_emb_message_to_channel(0xff0000, "You need to provide a reason for why you are removing this ban early\n\n" + cmdprefix + "unban @user the reason why you are removing this ban early", context)
        except(IndexError):
            await send_emb_message_to_channel(0xff0000, "That is not a valid user, you must @mention the player\n\n" + cmdprefix + "unban @user the reason why you are removing this ban", context)
    else:
        await send_emb_message_to_channel(0xff0000, context.message.author.mention + " you do not have access to this command", context)


# Unsubscribe
@Bot.command(name='unsubscribe', description="Allows users to leave the notification group, which removes them from the channel", brief="Leave the pickup channel", aliases=['unpug', 'unsub'], pass_context=True)
async def _unsubscribe(context):
    global accessRole
    if await command_is_in_wrong_channel(context): return  # To avoid cluttering and confusion, the Bot only listens to one channel
    if (accessRole is not None):
        try:
            await Bot.remove_roles(context.message.author, accessRole)
            await send_emb_message_to_user(0x00ff00, "Successfully removed role {0}".format(accessRole.name), context)
        except (discord.Forbidden, discord.HTTPException):
            pass
    else:  # role is None - this is typically caused by playerRoleID not matching any roles in the server
        print("ERROR MESSAGE: Something went wrong at " + time.time() + "\nDue to unsubscribe => role is None\n\nCheck playerRoleID is in server role id")
        await send_emb_message_to_user(0xff0000, "Something went wrong\nDue to unsubscribe => role is None\n\nCheck playerRoleID is in server role id\nPlease contact an admin", context)


# make bot commands case insensitive
@Bot.event
async def on_message(message):
    if await author_is_in_timeout(message): return # No bot for bad users
    message.content = message.content.lower()
    await Bot.process_commands(message)


# print and change presence when ready
@Bot.event
async def on_ready():
    global adminRole, adminRoleID, accessRole, playerRoleID, poolRole, poolRoleID, server, timeoutRole, timeoutRoleID
    await Bot.change_presence(game=Game(name="Ready"))
    print('Pickup Game Bot for Discord - Version 2.0')
    print('Logged in as: ' + Bot.user.name)
    print('Id: ' + Bot.user.id)
    server = Bot.get_server(id=discordServerID)
    adminRole = discord.utils.get(server.roles, id=adminRoleID)
    accessRole = discord.utils.get(server.roles, id=playerRoleID)
    poolRole = discord.utils.get(server.roles, id=poolRoleID)
    timeoutRole = discord.utils.get(server.roles, id=timeoutRoleID)
    # loop to check for banned users
    Bot.loop.create_task(check_bans())


Bot.run(token)
