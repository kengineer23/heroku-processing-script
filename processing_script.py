"""
@file app.py
@brief A Flask application for managing and monitoring air quality data and device modes.

This application receives air quality data, updates device modes, and communicates with an ESP32 device.
"""

from flask import Flask, request, jsonify
from pymongo import MongoClient
from threading import Thread, Lock
import time
import requests
import logging

# Set up logging
logging.basicConfig(level=logging.DEBUG)

# ESP32 endpoint URL (adjust this to your ESP32's IP address and endpoint)
ESP32_URL = 'http://192.168.1.8/update'

app = Flask(__name__)

# Global variable(s)
aqi = None
new_data = False

# MongoDB connection setup
client = MongoClient("mongodb+srv://isaac11:kanishk23@cluster0.bdljirk.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0")
db = client.sensor_data  # Database
action_collection = db.action  # Post data to this collection
sensorData_collection = db.readings # Receive data from collection
mode_collection = db.mode  # Receive data from collection

# Constants
valid_modes = ["AUTO", "TURBO", "SILENT", "SLEEP"]
AQI_MAX = 900
DUTY_CYCLE_MAX = 1900
DUTY_CYCLE_MIN_WORKING = 512
DUTY_CYCLE_MIN_IDLE = 412

# Shared variable(s)
# Declare a global variable 'mode' with an initial value AUTO
mode = "AUTO"
mode_lock = Lock()

def map_value(value, in_min, in_max, out_min, out_max):
    """
    @brief Scale input value from the input range to the output range.
    
    @param value Input value to be mapped.
    @param in_min Minimum of input range.
    @param in_max Maximum of input range.
    @param out_min Minimum of output range.
    @param out_max Maximum of output range.
    
    @return Mapped output value.
    """
    return (value - in_min) * (out_max - out_min) / (in_max - in_min) + out_min

@app.route('/receiveAQI', methods=['POST'])
def notify_aqi():
    """
    @brief Responds to updates in PM2.5 levels from incoming requests.

    This function receives air quality data (AQI) from a POST request and updates the global state.
    
    @return JSON response indicating success or error status.
    """
    global aqi, new_data
    latest_sensor_document = request.json
    app.logger.debug("Received data: %s", latest_sensor_document)

    if not latest_sensor_document:
        app.logger.error("No data received")
        return jsonify({'error': 'No data received'}), 400

    if 'PM2.5' not in latest_sensor_document:
        app.logger.error("PM2.5 data missing")
        return jsonify({'error': 'PM2.5 data missing'}), 400

    aqi = latest_sensor_document['PM2.5']
    new_data = True
    return jsonify({'status': 'success'}), 200

def ledcolor(pm2_5):
    """
    @brief Determine the LED color based on PM2.5 levels.

    @param pm2_5 PM2.5 level used to decide the LED color.
    
    @return Tuple of (red, green, blue) color values.
    """
    if(AQI_MAX > pm2_5 >= 150):
        red = int(255)
        green = int(0)
        blue = int(0)
    elif(150 > pm2_5 >= 100):
        red = int(255)
        green = int(255)
        blue = int(0)
    else:
        red = int(0)
        green = int(255)
        blue = int(0)
    return red, green, blue

def sendDatatoMongoDB(dutycycle, status, red, green, blue):
    """
    @brief Update the 'action' collection in MongoDB with new data.

    @param dutycycle Current duty cycle value.
    @param status Current status of the system.
    @param red Red component of the LED color.
    @param green Green component of the LED color.
    @param blue Blue component of the LED color.
    """
    document = {
        "DutyCycle": dutycycle,
        "ISAAC_STATUS": status,
        "RED": red,
        "GREEN": green,
        "BLUE": blue
    }
    
    # Insert the document into the collection
    result = action_collection.insert_one(document)

    # Print the inserted document's ObjectID
    print(f"Data inserted successfully: {result.inserted_id}")

def mode_settings(function_mode):
    """
    @brief Adjust system settings based on the selected mode.

    This function changes the duty cycle and other parameters according to the current mode.
    
    @param function_mode The mode to apply settings for.
    """
    global aqi, new_data
    red, green, blue = ledcolor(aqi)

    if function_mode == "AUTO":
        dutycycle = map_value(aqi, 0, AQI_MAX, 0, DUTY_CYCLE_MAX)
        status = "Normal"
    elif function_mode == "TURBO":
        dutycycle = DUTY_CYCLE_MAX
        status = "Fast"
    elif function_mode == "SILENT":
        dutycycle = DUTY_CYCLE_MIN_WORKING
        status = "Slow"
    elif function_mode == "SLEEP":
        dutycycle = DUTY_CYCLE_MIN_IDLE
        status = "Stationary"
    else:
        return  # Handle invalid mode gracefully
    if new_data:
        sendDatatoMongoDB(dutycycle, status, red, green, blue)
        new_data = False

def monitor_mode():
    """
    @brief Continuously monitor and apply mode settings.

    This function runs in a separate thread to ensure mode settings are applied every minute.
    """
    global mode
    while True:
        with mode_lock:
            current_mode = mode
    
        mode_settings(current_mode)
        time.sleep(60)

@app.route('/receiveMode', methods=['POST'])
def receive():
    """
    @brief Respond to POST requests by receiving the latest mode.

    This function updates the global mode based on incoming webhook payloads.
    
    @return JSON response indicating success or error status.
    """
    global mode 
    if request.is_json:
        content = request.get_json()

        print("Received webhook payload: ")
        print(content)
        if(content.get('operationType') == 'insert'):
            received_mode = content.get('Mode')
            print(f'Received mode: {mode}')
        if received_mode in valid_modes:
            with mode_lock:
                mode = received_mode
            return jsonify({'message': 'Valid mode received. Changing to {}'.format(received_mode)})
        else:
            return jsonify({'message': 'Invalid mode received'})
            
    else:
        return jsonify({'message': 'Invalid data format!'}), 400

@app.route('/notify_action', methods=['POST'])
def notify_action():
    """
    @brief Respond to POST requests and forward parameters to ESP32.

    This function receives action parameters and forwards them to an ESP32 device.
    
    @return JSON response indicating success or error status.
    """
    data = request.json
    app.logger.debug("Received data: %s", data)
    
    if not data:
        app.logger.error("No data received")
        return jsonify({'error': 'No data received'}), 400
    
    # Send the data to the ESP32
    try:
        response = requests.post(ESP32_URL, json=data)
        app.logger.debug("Response from ESP32: %s", response.text)
        
        if response.status_code == 200:
            return jsonify({'status': 'success'}), 200
        else:
            app.logger.error("Failed to notify ESP32, status code: %s", response.status_code)
            return jsonify({'error': 'Failed to notify ESP32'}), 500
    except Exception as e:
        app.logger.exception("Exception occurred while notifying ESP32")
        return jsonify({'error': str(e)}), 500

if __name__ == "__main__":
    # Start the monitoring thread
    monitor_thread = Thread(target=monitor_mode)
    monitor_thread.daemon = True  # Allow the thread to exit when the main program exits
    monitor_thread.start()
    
    app.run(host='0.0.0.0', port=5000, debug=True)
