import requests
import matplotlib.pyplot as plt
import numpy as np
import dateutil.parser
import datetime
import pytz
from threading import Thread
import time
import copy
from timebudget import timebudget

@timebudget
def get_data_from_server(data_name:str):
    return requests.get("http://rpigoe.local:8000/goeCharger/chargerlog/GoeCharger1/"+data_name).json()

@timebudget
def parse_data(data_name:str,tz):
    data = get_data_from_server(data_name)
    result = {"time":[],"value":[]}
    for i in range(len(data)):
        result["time"].append(dateutil.parser.parse(data[i].get("time")).astimezone(tz))
        try:
            result["value"].append(float(data[i].get("value")))
        except ValueError:
            try:
                if data[i].get("value") == "True":
                    result["value"].append(1)
                else:
                    result["value"].append(0)
            except ValueError:
                pass
    result["time"] = np.array(result["time"])
    result["value"] = np.array(result["value"])
    return result

def filter_time(data,min_date,max_date):
    new_data = {"time":[], "value": []}
    for i in range(len(data["time"])):
        if data["time"][i] > min_date and data["time"][i] < max_date:
            new_data["time"].append(data["time"][i])
            new_data["value"].append(data["value"][i])
    new_data
    for i in new_data:
        new_data[i] = np.array(new_data[i])
    return new_data

def read_data(data:list, min_date, max_date, tz):
    class BaseClass():
        def __init__(self):
            pass

    result = BaseClass()
    for i in range(len(data[0])):
        temp = parse_data(data[1][i], tz)
        temp = filter_time(temp, min_date, max_date)
        setattr(result, data[0][i], temp)
    return result

def get_my_data(min_date, max_date, tz):
    data_list = [
        ["nrg","power_delta","alw","amp","min_amp","battery_power","battery_soc","solar_power","car","grid_power"],
        ["nrg","power-delta","alw","amp","min-amp","battery-power","battery-soc","solar-power","car","grid-power"]]
    data = read_data(data_list, min_date, max_date, tz)

    min_power = copy.deepcopy(data.min_amp)
    min_power["value"] *= 690 # Drehstrom
    setattr(data, "min_power", min_power)

    power_setpoint = copy.deepcopy(data.amp)
    power_setpoint["value"] *= 690 # Drehstrom
    setattr(data, "power_setpoint", power_setpoint)
    return data

def main():
    tz = pytz.timezone("Europe/Berlin")
    date_now = datetime.datetime.now(tz)
    min_date = datetime.datetime(2020,5,date_now.day,0,0,0,0,tz)
    max_date = datetime.datetime(2022,5,date_now.day,23,59,59,0,tz)

    data = get_my_data(min_date,max_date,tz)

    thread_results = {"nrg":None,"power_delta":None,"alw":None,"amp":None}

    fig, ax = plt.subplots(5,1,sharex=True)
    l_nrg, = ax[0].plot(data.nrg["time"], data.nrg["value"], label="nrg")
    l_power_delta, = ax[0].plot(data.power_delta["time"], data.power_delta["value"], label="power_delta")
    l_power_setpoint, = ax[0].plot(data.power_setpoint["time"], data.power_setpoint["value"], label="power_setpoint")
    l_min_power, = ax[0].plot(data.min_power["time"], data.min_power["value"], label="min_power")
    l_battery_power, = ax[0].plot(data.battery_power["time"], data.battery_power["value"], label="battery_power")
    l_solar_power, = ax[0].plot(data.solar_power["time"], data.solar_power["value"], label="solar_power")
    l_grid_power, = ax[0].plot(data.grid_power["time"], data.grid_power["value"], label="grid_power")

    l_amp, = ax[1].plot(data.amp["time"], data.amp["value"], label="amp")
    l_min_amp, = ax[1].plot(data.min_amp["time"], data.min_amp["value"], label="min_amp")

    l_alw, = ax[2].plot(data.alw["time"], data.alw["value"], label="alw")

    l_battery_soc, = ax[3].plot(data.battery_soc["time"], data.battery_soc["value"], label="battery_soc")

    l_car, = ax[4].plot(data.car["time"], data.car["value"], label="car")

    for i in ax:
        i.legend()

    if True:
        plt.show()
    else:
        plt.pause(0.01)
        plt.tight_layout()

        while True:
            data = get_my_data(min_date,max_date,tz)

            l_nrg.set_xdata(data.nrg["time"])
            l_nrg.set_ydata(data.nrg["value"])
            l_power_delta.set_xdata(data.power_delta["time"])
            l_power_delta.set_ydata(data.power_delta["value"])
            l_amp.set_xdata(data.amp["time"])
            l_amp.set_ydata(data.amp["value"])
            l_alw.set_xdata(data.alw["time"])
            l_alw.set_ydata(data.alw["value"])

            plt.pause(0.01)
            time.sleep(2)

if __name__ == '__main__':
    main()
