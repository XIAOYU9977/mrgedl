#!/bin/bash
while true
do
    echo "Starting Merge Bot..."
    python3 -m bot.main
    echo "Bot crashed or stopped with exit code $?. Restarting in 5 seconds..."
    sleep 5
done
