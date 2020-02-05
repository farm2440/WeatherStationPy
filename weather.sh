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
    INTERFACE=$(ifconfig | grep 'ppp')
    RESULT=$?
    echo "no ppp..." >> /home/pi/log2
    echo "no ppp..."
done
echo "ppp is present!" >> log2
echo "ppp is present!"

# wait for WiFi network is connected. SSID here is Etherino and should be correctly updated
RESULT=1
until [ $RESULT -eq 0 ]
do
    sleep 5
    TEST=$(iwconfig wlan0 | grep Etherino)
    RESULT=$?
    echo "no Etherino WiFi network..." >> /home/pi/log2
    echo "no Etherino WiFi network..."
done
echo "Connected to WiFi SSID=Etherinp!" >> log2
echo "Connectes to WiFi SSID=Etherino!"


runuser -l pi -c 'python /home/pi/weather.py &'

