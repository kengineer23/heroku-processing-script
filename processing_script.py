"""
@file app.py
@brief A Flask application for managing and monitoring air quality data and device modes.

This application receives air quality data, updates device modes, and communicates with an ESP32 device.
"""

from flask import Flask, request, jsonify,g
from pymongo import MongoClient 
from threading import Thread, Lock
import time
import requests
import logging
import ipaddress
import struct

# Set up logging
logging.basicConfig(level=logging.DEBUG)

# Global variable to store the URL
esp32_url = ''

app = Flask(__name__)

# Global variable(s)
aqi = int()
new_data = False

# MongoDB connection setup
client = MongoClient("mongodb+srv://isaac11:kanishk23@cluster0.bdljirk.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0")
db = client.sensor_data  # Database
action_collection = db.action  # Post data to this collection
sensorData_collection = db.readings # Receive data from collection
mode_collection = db.mode  # Receive data from collection
device_id_collection = client.device_id

# Shared data storage and lock
data_store = None
data_lock = Lock()

@app.route('/notify_action', methods=['POST'])
def notify_action():
    """
    This route receives data from MongoDB trigger and stores it for the ESP32.
    """
    data = request.json

    payload = data['payload']

    with data_lock:
        global data_store
        data_store = payload

    return jsonify({"status": "success"}), 200

@app.route('/get_data', methods=['GET'])
def get_data():
    """
    This route allows the ESP32 to retrieve its data.
    """
    with data_lock:
        global data_store
        if data_store is not None:
            payload = data_store
            data_store = None  # Clear the data after it is retrieved
            return jsonify({"payload": payload}), 200
        else:
            return jsonify({"error": "No data available"}), 404
        
@app.route('/receiveDeviceIP', methods=['POST'])
def receiveIP():
    global esp32_url
    # Check if the request is JSON
    if not request.is_json:
        return jsonify({'status': 'error', 'message': 'Invalid JSON'}), 400
    
    print("Received data")

    # Parse JSON data
    received_data = request.get_json()

    # Validate required fields
    if 'document' not in received_data:
        return jsonify({'status': 'error', 'message': 'Missing document'}), 400

    device_ip = received_data['document']['IP Address']
    # URL to establish one-to-one connection with ESP32
    with mode_lock:
        esp32_url = f"http://{device_ip}/update"
    print(esp32_url)

    return jsonify({'message': 'Device IP received successfully!', 'device_ip': device_ip}), 200

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
def receive_aqi():
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


    aqi = int(latest_sensor_document['document']['PM2.5']['$numberInt'])
    print(aqi)
    #new_data = True
    sendDatatoMongoDB()
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

def sendDatatoMongoDB():
    """
    @brief Update the 'action' collection in MongoDB with new data.

    @param dutycycle Current duty cycle value.
    @param status Current status of the system.
    @param red Red component of the LED color.
    @param green Green component of the LED color.
    @param blue Blue component of the LED color.
    """
    global aqi, mode
    red, green, blue = ledcolor(aqi)

    if mode == "AUTO":
        dutycycle = map_value(aqi, 0, AQI_MAX, 0, DUTY_CYCLE_MAX)
        status = "Normal"
    elif mode == "TURBO":
        dutycycle = DUTY_CYCLE_MAX
        status = "Fast"
    elif mode == "SILENT":
        dutycycle = DUTY_CYCLE_MIN_WORKING
        status = "Slow"
    elif mode == "SLEEP":
        dutycycle = DUTY_CYCLE_MIN_IDLE
        status = "Stationary"
    else:
        return  # Handle invalid mode gracefully

    # Create a document to be inserted into the collection
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

'''
def mode_settings(function_mode):
    """
    @brief Adjust system settings based on the selected mode.

    This function changes the duty cycle and other parameters according to the current mode.
    
    @param function_mode The mode to apply settings for.
    """
    print('Function mode_settings being executed')
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
    else:
        print('No new data')
'''

@app.route('/receiveMode', methods=['POST'])
def receive():
    """
    @brief Respond to POST requests by receiving the latest mode.

    This function updates the global mode based on incoming webhook payloads.

    mode_lock ensures thread-safe access to the global 'mode' variable,
    preventing race conditions by serializing read and write operations
    across multiple threads. 

    Using 'with' the process of acquiring and releasing the lock is done automatically.
    Once the statements within the with block are executed, the lock is released for other threads to acquire.
    
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
'''
@app.route('/notify_action', methods=['POST'])
def notify_action():
    """
    @brief Respond to POST requests and forward parameters to ESP32.

    This function receives action parameters and forwards them to an ESP32 device.
    
    @return JSON response indicating success or error status.
    """
    data = request.json
    print(data)
    app.logger.debug("Received data: %s", data)
    
    if not data:
        print('1')
        app.logger.error("No data received")
        return jsonify({'error': 'No data received'}), 400

    app.logger.debug('Sending data to ESP32')
    try:
        response = requests.post(esp32_url, json=data, timeout=10)
        app.logger.debug("Response from ESP32: %s", response.text)
    
        if response.status_code == 200:
            return jsonify({'status': 'success'}), 200
        else:
            app.logger.error("Failed to notify ESP32, status code: %s", response.status_code)
            return jsonify({'error': 'Failed to notify ESP32', 'status_code': response.status_code, 'response_text': response.text}), 500
    except requests.exceptions.RequestException as e:
        app.logger.exception("Exception occurred while notifying ESP32: %s", str(e))
        return jsonify({'error': str(e)}), 500

'''


if __name__ == "__main__":
    # Start the monitoring thread
    '''
    monitor_thread = Thread(target=monitor_mode)
    monitor_thread.daemon = True  # Allow the thread to exit when the main program exits
    monitor_thread.start()
    '''
    app.run(host='0.0.0.0', port=5000, debug=True)
