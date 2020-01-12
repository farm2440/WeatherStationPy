#!/bin/sh

#put some time stamp to log file
echo > log
echo "starting connect_3g.sh script..." >> /home/pi/log
date >> /home/pi/log

# At first the  3G modem usb dongle presents itself as a Quallcom usb mass storage device
# and after some time it's shown as Huawei modem. We have to wait for this to happen before
# executing the dial command. Check if it's connected to USB
RESULT=1
until [ $RESULT -eq 0 ]
do
    sleep 5
    USBDEVICES=$(lsusb | grep '12d1:1001')
    RESULT=$?
    echo "no modem..." >> /home/pi/log
    echo "no modem..."
done
echo "modem is present!" >> log
echo "modem is present!"


# the modem is present. Let's dial
RESULT=1
until [ $RESULT -eq 0 ]
do
    $(wvdial 3gconnect)
    RESULT=$?
    echo "dialing..." >> /home/pi/log
    echo "dialing..."
    sleep 5
done
