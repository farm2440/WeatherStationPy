#!/usr/bin/env python
from socket import *
# from gpiozero import LED  TODO
import datetime
import time
import re
import paho.mqtt.client as mqtt
from socket import error as socket_error

# ptt = LED(4)
# ptt.off()   TODO

# Every time when broadcast message is received from a sensor the data from it is parsed and stored to aprs_data and
# mqtt_data dictionaries. Tke keys are var names in format <mac address>_<data type>. Values are the value measured by
# the sensor. For example 1d:aa:44_temp=23. If data for var with name already in dict is received the value is updated.
# Data from dicts is sent periodically and after this dictionaries are cleared.
aprs_data = {}
mqtt_data = {}
aprs_tx_period = datetime.timedelta(minutes=2)
mqtt_tx_period = datetime.timedelta(minutes=2)
aprs_last_tx_timestamp = datetime.datetime.now()
mqtt_last_tx_timestamp = datetime.datetime.now()

aprs_var_name_translation = {
    '1d:aa:44_temp': ' T1=',  # Garage
    '1d:ab:43_temp': ' T2=',  # Fl.2
    '1d:a7:d1_temp': ' T3=',  # Fl.1
    '77:b7:bf_P': ' P=',  # Atm. pressure
    '77:b7:bf_temp': ' Tout=',  # Temperature outside
    '77:b7:bf_hum': ' Rh=',  # Humidity outside
    '77:b7:bf_tempBMP': ' Tin',  # Temperature inside, measured on sensor board
    '77:b7:bf_wd': ' WD=',  # Wind direction
    '77:b7:bf_ws': ' WS=',  # Wind speed
    '77:b7:bf_wg': ' WG=',  # Wind gusts
    '77:b7:bf_rain1h': ' R1=',  # Rain for the last 1 hour
    '77:b7:bf_rain24h': ' R24=',  # Rain for the last 24 hours
    '77:b7:bf_Ubat': ' U='    # Battery voltage
}

# TX20 wind sensors sends a number from 0 to 15 for wind direction. Here is conversion to string name
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
# interface_ip = str(INADDR_ANY)         # Sensors obtain their IP by DHCP starting from 192.168.152.100
interface_ip = str("192.168.152.91")    # RaspberryPi board has fixed IP address in LAN

s = socket(AF_INET, SOCK_DGRAM)
s.bind(("", mcast_port))
mreq = inet_aton(mcast_grp) + inet_aton(interface_ip)
s.setsockopt(IPPROTO_IP, IP_ADD_MEMBERSHIP, str(mreq))

# prepare MQTT broker connection
# https://customer.cloudmqtt.com/login
# https://1sheeld.com/mqtt-protocol/
client = mqtt.Client(client_id='*************') 
client.username_pw_set('******', '*********')


def on_connect(client, userdata, flags, rc):
    # This function does nothing. Just for information
    if rc == 0:
        print("Connected to broker OK!")
    else:
        print("Failed connecting to broker. Returned code:", rc)
    return 0


client.on_connect = on_connect


def aprs(aprs_data_string):
    # This function takes a string which should contain sensors data and transmit, adds APRS header including
    # APRS symbol, GPS coordinates and transmits it over radio. PTT is triggered by GPIO  .
    # Direwolf shall be started on on power on. This function connects to Direwolf on port 8001.

    print("Sending APRS:", aprs_data_string)
    return 0

    soc = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    soc.connect(('127.0.0.1', 8001))

    # msg_body = '!4323.28H/02789.64E>TEST'
    # msg_body = '!4313.98NW02753.78E# TEST 6'
    # msg_body = '!4313.98N/02753.78Ey c999s999g008t054r001 TEST 20'
    # the leter after N  between long and alt is the overlay char. / for none
    # the leter after E after long and alt is the symbol. _ weather station, y house with yagi, > car

    #               DST       SRC      DIGI-->
    callsigns = ['LZ2SMX9 ', 'LZ2SMX3', 'WIDE2 1']
    # msg_header = '!4313.98N/02753.78Ey '  # vazrajdane 66, house with Yagi
    msg_header = '!4307.46N/02744.14Ey '  # Zdravets, house with Yagi

    # msg_body = 'T_garage=15 T_fl.2=23 Tfl.1=18 P=1008hPa   TEST 11'
    msg_body = aprs_data_string

    msg = chr(0xC0)
    msg += chr(0x00)
    for i in range(0, len(callsigns)):
        cs = callsigns[i]
        for j in range(0, 6):
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
    msg += msg_header
    msg += msg_body
    msg += chr(0xC0)

    print('Sending APRS data:', msg_body)
#    ptt.on()
    time.sleep(0.1)
    soc.send(msg)
    time.sleep(2)
#    ptt.off() TODO
    return 0


# Receive multicast data and send it to MQTT broker  loop
while 1:
    # wait for multicast packet
    data, address = s.recvfrom(1024)
    dt = datetime.datetime.now()
    print dt
    print(data)
    print

    # parse data inside multicast packet
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
    update_rain = False  # this flag is turned to True. This is to update rain values only when new data is available

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
                update_rain = True
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
    else:
        continue    # Maybe malformed data

    # store parsed data aprs_data and mqtt_data dictionaries
    if tempAM != -100:
        aprs_data[mac + '_' + 'temp'] = tempAM
        mqtt_data[mac + '_' + 'temp'] = tempAM
    if hum != -100:
        aprs_data[mac + '_' + 'hum'] = hum
        mqtt_data[mac + '_' + 'hum'] = hum
    if pressure != -100:
        aprs_data[mac + '_' + 'P'] = pressure
        mqtt_data[mac + '_' + 'P'] = pressure
    if tempBMP != -100:
        aprs_data[mac + '_' + 'tempBMP'] = tempBMP
        mqtt_data[mac + '_' + 'tempBMP'] = tempBMP
    if ubat != -100:
        aprs_data[mac + '_' + 'Ubat'] = ubat
        mqtt_data[mac + '_' + 'Ubat'] = ubat
    #  process new rain data
    if update_rain:
        rain_1h = 0
        if len(rain_data_1h) != 0:
            for t in rain_data_1h:
                rain_1h += int(rain_data_1h[t])
        aprs_data[mac + '_' + 'rain1h'] = rain_1h
        mqtt_data[mac + '_' + 'rain1h'] = rain_1h
        rain_24h = 0
        if len(rain_data_24h) != 0:
            for t in rain_data_24h:
                rain_24h += int(rain_data_24h[t])
        aprs_data[mac + '_' + 'rain24h'] = rain_24h
        mqtt_data[mac + '_' + 'rain24h'] = rain_24h
    # process wind data
    if wind_speed != -100:
        aprs_data[mac + '_' + 'ws'] = average_speed
        aprs_data[mac + '_' + 'wg'] = gusts
        aprs_data[mac + '_' + 'wd'] = wind_dir_dictionary[average_dir]
        mqtt_data[mac + '_' + 'ws'] = average_speed
        mqtt_data[mac + '_' + 'wg'] = gusts
        mqtt_data[mac + '_' + 'wd'] = wind_dir_dictionary[average_dir]

    # check if its time to send to MQTT broker.
    timestamp = datetime.datetime.now()
    if (timestamp - mqtt_last_tx_timestamp) > mqtt_tx_period:
        try:
            client.connect('farmer.cloudmqtt.com', 10791)
            print('Publish MQTT :')
            for mqtt_data_key in mqtt_data:
                client.publish(mqtt_data_key, mqtt_data[mqtt_data_key])
                print(mqtt_data_key, '=', mqtt_data[mqtt_data_key])
            client.disconnect()
            mqtt_data.clear()
            mqtt_last_tx_timestamp = timestamp

        except socket_error as err:
            print("ERR: Failed publish data to broker")
            print err
            print

    # check if its time to transmit APRS over radio.
    timestamp = datetime.datetime.now()
    aprs_message = ''
    if (timestamp - aprs_last_tx_timestamp) > aprs_tx_period:
        aprs_last_tx_timestamp = timestamp
        for aprs_data_key in aprs_data:
            if aprs_data_key in aprs_var_name_translation.keys():
                aprs_message += aprs_var_name_translation[aprs_data_key]
                aprs_message += aprs_data[aprs_data_key]
        aprs_data.clear()
        aprs(aprs_message)