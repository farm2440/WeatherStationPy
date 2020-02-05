#!/usr/bin/env python
from socket import *
from gpiozero import LED
import datetime
import time
import re
import paho.mqtt.client as mqtt
from socket import error as socket_error

ptt = LED(4)
ptt.off()

# Every time when broadcast message is received from a sensor the data from it is parsed and stored to aprs_data and
# mqtt_data dictionaries. Tke keys are var names in format <mac address>_<data type>. Values are the value measured by
# the sensor. For example 1d:aa:44_temp=23. If data for var with name already in dict is received the value is updated.
# Data from dicts is sent periodically and after this dictionaries are cleared.
aprs_data = {}
mqtt_data = {}
aprs_tx_period = datetime.timedelta(minutes=10, seconds=19)
mqtt_tx_period = datetime.timedelta(minutes=5)
aprs_last_tx_timestamp = datetime.datetime.now()
mqtt_last_tx_timestamp = datetime.datetime.now()

mac_outside_sensor = '77:b7:bf'

aprs_var_name_translation = {
    '1d:aa:44_temp': ' Tg=',  # Garage
    '1d:ab:43_temp': ' T2=',  # Fl.2
    '1d:a7:d1_temp': ' T1=',  # Fl.1
    '77:b7:bf_P': ' P=',  # Atm. pressure
    '77:b7:bf_temp': ' Tout=',  # Temperature outside
    '77:b7:bf_hum': ' Rh=',  # Humidity outside
    '77:b7:bf_tempBMP': ' Tin=',  # Temperature inside, measured on sensor board
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

# atmospheric pressure altitude adjustment 12hPa for 100 meter
ALTITUDE_ADJUST = 2 * 12

# prepare for multicast receive
mcast_port = 8888
mcast_grp = "224.0.0.120"
# interface_ip = str(INADDR_ANY)         # Sensors obtain their IP by DHCP starting from 192.168.152.100
interface_ip = str("192.168.152.90")    # RaspberryPi board has fixed IP address in LAN

s = socket(AF_INET, SOCK_DGRAM)
s.bind(("", mcast_port))
mreq = inet_aton(mcast_grp) + inet_aton(interface_ip)
s.setsockopt(IPPROTO_IP, IP_ADD_MEMBERSHIP, str(mreq))

# prepare MQTT broker connection
# https://customer.cloudmqtt.com/login
# https://1sheeld.com/mqtt-protocol/
client = mqtt.Client(client_id='farmer.cloudmqtt.com')
client.username_pw_set('*********', '********')

# weather station APRS format . Check aprs_notes.txt file for details
wx_data = [8]


def clear_wx_data():
    del wx_data[:]
    wx_data.append('_...')       # 0 (_) wind direction in degrees
    wx_data.append('/...')       # 1 (/) wind in mph. M/S * 2.237
    wx_data.append('g...')       # 2 (g)
    wx_data.append('t...')       # 3 (t) temperature in Farenheit. (1°C × 9/5) + 32 = 33.8°F
    wx_data.append('r...')       # 4 (r) rain in last hour  (in hundreths of an inch) 1 mm to inch = 0.03937 inch
    wx_data.append('p...')       # 5 (p)
    wx_data.append('h..')        # 6 (h)
    wx_data.append('b.....')     # 7 (b) The barometric pressure in tenths of millibars


clear_wx_data()


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
    # Direwolf shall be started on on power on. This function connects to Direwolf (software TNC) on port 8001.

    print("Sending APRS:", aprs_data_string)
    print
    # msg_body = '!4323.28H/02789.64E>TEST'
    # msg_body = '!4313.98NW02753.78E# TEST 6'
    # msg_body = '!4313.98N/02753.78Ey c999s999g008t054r001 TEST 20'
    # the leter after N  between long and alt is the overlay char. / for none
    # the leter after E after long and alt is the symbol. _ weather station, y house with yagi, > car

    #               DST       SRC      DIGI-->
    callsigns = ['LZ2SMX9 ', 'LZ2SMX3', 'WIDE2 1']
    # msg_header = '!4313.98N/02753.78Ey '  # vazrajdane 66, house with Yagi
    msg_header = '!4307.46N/02744.14Ey '  # Zdravets, house with Yagi
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

    try:
        soc = socket(AF_INET, SOCK_STREAM)
        soc.connect(('127.0.0.1', 8001))

        ptt.on()
        time.sleep(0.1)
        soc.send(msg)
        time.sleep(2)
        ptt.off()
    except socket_error as err:
        print("ERR: Failed APRS trasmission! Check that Direwolf is running.")
        print err
        print

    return 0


# Receive multicast data and send it to MQTT broker/APRS  loop
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
    wind_speed_sum = 0
    average_speed_ms = 0
    average_speed_mph = 0
    average_dir = 0
    gusts_raw = 0
    gusts_ms = 0
    gusts_mph = 0
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
                    wind_speed = float(nums[2])
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
                        wind_speed_sum += spd
                        if spd > gusts_raw:
                            gusts_raw = spd

                    average_speed_mph = int(wind_speed_sum * 0.2237 / len(wind_speed_samples))
                    average_speed_ms = int(wind_speed_sum / (len(wind_speed_samples) * 10))
                    gusts_ms = int(gusts_raw/10)
                    gusts_mph = int(gusts_raw * 0.2237)
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

    # store parsed data to wx_data, aprs_data and mqtt_data dictionaries
    if tempAM != -100:
        aprs_data[mac + '_' + 'temp'] = tempAM
        mqtt_data[mac + '_' + 'temp'] = tempAM
        if mac == mac_outside_sensor:
            wx_data[3] = 't%0*d' % (3, float(tempAM)*9/5+32)  # 3 (t) temperature in Farenheit. (1°C × 9/5) + 32 = 33.8°F
    if hum != -100:
        aprs_data[mac + '_' + 'hum'] = hum
        mqtt_data[mac + '_' + 'hum'] = hum
        if mac == mac_outside_sensor:
            wx_data[6] = 'h%0*d' % (2, hum)  # 6 (h)
    if pressure != -100:
        aprs_data[mac + '_' + 'P'] = pressure + ALTITUDE_ADJUST
        mqtt_data[mac + '_' + 'P'] = pressure + ALTITUDE_ADJUST
        wx_data[7] = 'b%0*d' % (5, (pressure + ALTITUDE_ADJUST) * 10)     # 7 (b) The barometric pressure in tenths of millibars
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
        wx_data[4] = 'r%0*d' % (3, rain_1h)     # 4 (r) rain in last hour  (in hundreds of an inch)
                                                # 1mm to inch=0.03937 inch
        rain_24h = 0
        if len(rain_data_24h) != 0:
            for t in rain_data_24h:
                rain_24h += int(rain_data_24h[t])
        aprs_data[mac + '_' + 'rain24h'] = rain_24h
        mqtt_data[mac + '_' + 'rain24h'] = rain_24h
        wx_data[5] = 'p%0*d' % (3, rain_24h)     # 5 (p) rain in last 24 hours  (in hundreths of an inch)
                                                 # 1 mm to inch = 0.03937 inch
    # process wind data
    if wind_speed != -100:
        aprs_data[mac + '_' + 'ws'] = average_speed_ms
        aprs_data[mac + '_' + 'wg'] = gusts_ms
        aprs_data[mac + '_' + 'wd'] = wind_dir_dictionary[average_dir]
        mqtt_data[mac + '_' + 'ws'] = average_speed_ms
        mqtt_data[mac + '_' + 'wg'] = gusts_ms
        mqtt_data[mac + '_' + 'wd'] = wind_dir_dictionary[average_dir]
        wx_data[0] = '_%0*d' % (3, average_dir * 22.5)     # 0 (_) wind direction in degrees
        wx_data[1] = '/%0*d' % (3, average_speed_mph)  # 1 (/) wind in mph. M/S * 2.237
        wx_data[2] = 'g%0*d' % (3, gusts_mph)  # 2 (g) wind gusts in mph. M/S * 2.237

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
            print
        except socket_error as err:
            print("ERR: Failed publish data to broker")
            print err
            print

    # check if its time to transmit APRS over radio.
    timestamp = datetime.datetime.now()
    aprs_message = ''       # all data in one string in format <var>=<value>
    aprs_wx_message = ''    # weather data in aprs weather station format
    aprs_wx_comment = ''    # room temperatures are added as comment to weather data
    if (timestamp - aprs_last_tx_timestamp) > aprs_tx_period:
        aprs_last_tx_timestamp = timestamp
        for aprs_data_key in aprs_data:
            if aprs_data_key in aprs_var_name_translation.keys():
                # prepare aprs_wx_comment
                aprs_message += aprs_var_name_translation[aprs_data_key]  # var name =
                aprs_message += str(aprs_data[aprs_data_key]) # value
                # prepare aprs_wx_message
                if aprs_var_name_translation[aprs_data_key] == ' Tg=':  # Garage
                    aprs_wx_comment += (' Tg=' + str(aprs_data[aprs_data_key]))
                if aprs_var_name_translation[aprs_data_key] == ' T2=':   # Fl.2
                    aprs_wx_comment += (' T2=' + str(aprs_data[aprs_data_key]))
                if aprs_var_name_translation[aprs_data_key] == ' T1=':  # Fl.1
                    aprs_wx_comment += (' T1=' + str(aprs_data[aprs_data_key]))
                if aprs_var_name_translation[aprs_data_key] == ' U=':  # Battery voltage
                    aprs_wx_comment += (' U=' + str(aprs_data[aprs_data_key]))
        # prepare aprs_wx_message
        for tag in wx_data:
            aprs_wx_message += tag
        aprs_wx_message += aprs_wx_message
        clear_wx_data()
        aprs_data.clear()
        # we can choose which format data to send
        aprs(aprs_message)
        #aprs(aprs_wx_message)

