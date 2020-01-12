#!/bin/sh

#put some time stamp to log file
echo > log2
date >> /home/pi/log2

# waiting for 3G modem to establish the connection. When this is done,
# an interface ppp0 shall be visible in ifconfig command output
RESULT=1
until [ $RESULT -eq 0 ]
do
    sleep 5
    USBDEVICES=$(ifconfig | grep 'ppp')
    RESULT=$?
    echo "no ppp..." >> /home/pi/log2
    echo "no ppp..."
done
echo "ppp is present!" >> log2
echo "ppp is present!"

#runuser -l pi -c '/home/pi/direwolf/direwolf &'
runuser -l pi -c 'python /home/pi/weather.py &'

