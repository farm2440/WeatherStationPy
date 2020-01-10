#!/usr/bin/env python
from socket import *
from gpiozero import LED
import datetime
import re
import paho.mqtt.client as mqtt
from socket import error as socket_error

ptt = LED(4)
ptt.off()
aprs_counter = 1

wind_dir_dictionary = {
    0:  "N",
    1:  "NNE",
    2:  "NE",
    3:  "ENE",
    4:  "E",
    5:  "ESE",
    6:  "SE",
    7:  "SSE",
    8:  "S",
    9:  "SSW",
    10: "SW",
    11: "WSW",
    12: "W",
    13: "WNW",
    14: "NW",
    15: "NNW"
}
# average wind direction and speed over last WIND_AVERAGED values stored in wind_dir_samples[] and wind_speed_samples[]
WIND_AVERAGED = 5
wind_speed_samples = []
wind_dir_samples = []

# historical rain data is stored in two dicts for last hour and for last 24 hours.
rain_data_1h = {}
rain_data_24h = {}

# prepare for multicast receive
mcast_port = 8888
mcast_grp = "224.0.0.120"
#interface_ip = str(INADDR_ANY)
interface_ip = str("192.168.152.90")

s = socket(AF_INET, SOCK_DGRAM)
s.bind(("", mcast_port))
mreq = inet_aton(mcast_grp) + inet_aton(interface_ip)

s.setsockopt(IPPROTO_IP, IP_ADD_MEMBERSHIP, str(mreq))

# prepare MQTT broker connection
# https://customer.cloudmqtt.com/login
# https://1sheeld.com/mqtt-protocol/



def on_connect(client, userdata, flags, rc):
    if rc == 0:
        print("Connected to broker OK!")
    else:
        print("Failed connecting to broker. Returned code:", rc)
    return 0

def aprs(data):
    soc = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    soc.connect(('127.0.0.1', 8001))

    # msgBody = '!4323.28H/02789.64E>TEST'
    # msgBody = '!4313.98NW02753.78E# TEST 6'
    # msgBody = '!4313.98N/02753.78Ey c999s999g008t054r001 TEST 20'
    # the leter after N  between long and alt is the overlay char. / for none
    # the leter after E after long and alt is the symbol. _ weather station, y house with yagi, > car

    #               DST       SRC      DIGI-->
    callsigns = ['LZ2SMX9 ', 'LZ2SMX3', 'WIDE2 1']
    # msgHeader = '!4313.98N/02753.78Ey '  # vazrajdane 66, house with Yagi
    msgHeader = '!4307.46N/02744.14Ey '  # Zdravets, house with Yagi

    # msgBody = 'T_garage=15 T_fl.2=23 Tfl.1=18 P=1008hPa   TEST 11'
    msgBody = data

    msg = chr(0xC0)
    msg += chr(0x00)
    for i in range(0, len(callsigns)):
        cs = callsigns[i]
        for j in range(0, 6):
            t = cs[j]
            msg += chr(ord(cs[j]) << 1)
        ssid = ord(cs[6])
        ssid <<= 1
        ssid += 0x60
        if i == len(callsigns) - 1:
            # Last address
            ssid += 1
        msg += chr(ssid)

    msg += chr(0x03)
    msg += chr(0xF0)
    msg += msgHeader
    msg += msgBody
    msg += chr(0xC0)

    prit('Sending APRS data...')
    ptt.on()
    time.sleep(0.1)
    soc.send(msg)
    time.sleep(2)
    ptt.off()
    return 0


client = mqtt.Client(client_id='******')
client.username_pw_set('******', '******')
client.on_connect = on_connect


# Receive multicast data and send it to MQTT broker  loop
while 1:
    # wait for multicast packet
    data, address = s.recvfrom(1024)
    dt = datetime.datetime.now()
    print dt
    print(data)
    print

    # parse data
    tempAM = -100
    hum = -100
    wind_dir = -100
    wind_speed = -100
    average_speed = 0
    average_dir = 0
    gusts = 0
    tempBMP = -100
    pressure = -100
    ubat = -100
    mac = '00:00:00'  # last 3 bytes only
    hour = datetime.timedelta(minutes=60)
    day = datetime.timedelta(hours=24)
    publish_rain = False

    lines = data.splitlines()
    if lines[0].startswith('MAC='):
        ln = lines[0]
        mac = ln[4:]
        for ln in lines[1:]:
            if ln.startswith("AM2302:"):
                # get AM2302 temp and Rh
                nums = re.findall(r'-?\d+', ln)
                tempAM = nums[1]
                hum = nums[2]
            if ln.startswith("TX20:"):
                # get TX20 wind data
                # calculate average wind direction, speed and gusts over last WIND_AVERAGED values stored
                # in wind_dir_samples[] and wind_speed_samples[]
                if ln[-3:] != "ERR":
                    nums = re.findall(r'-?\d+', ln)
                    wind_speed = int(nums[2])/10
                    wind_dir = int(nums[1])
                    wind_dir_samples.append(wind_dir)
                    wind_speed_samples.append(wind_speed)
                    if len(wind_dir_samples) > WIND_AVERAGED:
                        wind_dir_samples.pop(0)

                    if len(wind_speed_samples) > WIND_AVERAGED:
                        wind_speed_samples.pop(0)

                    for d in wind_dir_samples:
                        average_dir += d

                    average_dir = average_dir / len(wind_dir_samples)
                    for spd in wind_speed_samples:
                        average_speed += spd
                        if spd > gusts:
                            gusts = spd

                    average_speed = average_speed / len(wind_speed_samples)
            if ln.startswith("BMP180:"):
                nums = re.findall(r'-?\d+', ln)
                tempBMP = nums[1]
                pressure = nums[2]

            if ln.startswith("RAIN:"):
                publish_rain = True
                nums = re.findall(r'-?\d+', ln)
                rain = nums[0]
                timestamp = datetime.datetime.now()
                if rain != 0:
                    # add new data to dicts
                    rain_data_1h[timestamp] = rain
                    rain_data_24h[timestamp] = rain
                # delete from dictionaries old data
                ts_to_clear = []
                for t in rain_data_1h:
                    if (timestamp-t) > hour:
                        ts_to_clear.append(t)  # find timestamps to be removed
                for t in ts_to_clear:
                    rain_data_1h.pop(t)  # remove data
                ts_to_clear = []
                for t in rain_data_24h:
                    if (timestamp-t) > day:
                        ts_to_clear.append(t)
                for t in ts_to_clear:
                    rain_data_24h.pop(t)
            if ln.startswith("Ubat:"):
                nums = re.findall(r'[-+]?\d*\.*\d+', ln)
                ubat = nums[0]

        # send to MQTT broker
        try:
            client.connect('farmer.cloudmqtt.com', 10791)

            if tempAM != -100:
                client.publish(mac + '_' + 'temp', tempAM)
            if hum != -100:
                client.publish(mac + '_' + 'hum', hum)
            if pressure != -100:
                client.publish(mac + '_' + 'P', pressure)
            if tempBMP != -100:
                client.publish(mac + '_' + 'tempBMP', tempBMP)
            if ubat != -100:
                client.publish(mac + '_' + 'Ubat', ubat)
            #  publish rain
            if publish_rain:
                rain_1h = 0
                if len(rain_data_1h) != 0:
                    for t in rain_data_1h:
                        rain_1h += int(rain_data_1h[t])
                client.publish(mac + '_' + 'rain1h', rain_1h)
                rain_24h = 0
                if len(rain_data_24h) != 0:
                    for t in rain_data_24h:
                        rain_24h += int(rain_data_24h[t])
                client.publish(mac + '_' + 'rain24h', rain_24h)
            # publish wind
            if wind_speed != -100:
                client.publish(mac + '_' + 'ws', average_speed)
                client.publish(mac + '_' + 'wg', gusts)
                client.publish(mac + '_' + 'wd', wind_dir_dictionary[average_dir])
            client.disconnect()
        except socket_error as err:
            print("ERR: Failed publish data to broker")
            print err
            print

        # send APRS
        aprs_counter += 1
        if (aprs_counter%5)==0:
            aprs('test data msg ', aprs_counter)