#!/bin/bash

echo "Initiating run bot script"

cd ~/PugBot-for-Discord
if pgrep -f 'pugbot.py'
then
	echo "    PugBot is currently running"
	echo "    Stopping the existing process first. This action has been logged"
	nows=$(date +"%m%d%Y.%H%M%S")
	echo "A force stop has occurred at $nows" >> logs/force_stops
	`kill $(pgrep -f 'pugbot.py')`
fi

echo "    Reading and incrementing the debug counter"
typeset -i number_of_restarts=$(head -n 1 pugbot.out.log)
if ((number_of_restarts > 4))
then
	echo "    Bot has restarted too many times"
	echo "    Rotating the log directory to avoid capacity limits"
	sudo bash -c "rm -f /home/ubuntu/PugBot-for-Discord/logs/pugbot.out*"
	sudo bash -c "rm -f /home/ubuntu/PugBot-for-Discord/logs/pugbot.err*"
	number_of_restarts=0
else
    number_of_restarts=$((number_of_restarts + 1))
fi

echo "    Timestamping and saving the old log files"
now=$(date +"%m%d%Y.%H%M%S")
mv pugbot.err.log logs/pugbot.err.$now
mv pugbot.out.log logs/pugbot.out.$now

echo "    Creating a new output file and adding the debug counter to it"
echo "$number_of_restarts" > pugbot.out.log

echo "    Starting the bot"
python3 pugbot.py >> pugbot.out.log 2>> pugbot.err.log < /dev/null &

echo "The run bot script is complete"
echo "You may now exit the PuTTY session"
