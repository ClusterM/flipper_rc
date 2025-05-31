# Flipper Zero Remote Control integration for Home Assistant

Got a Flipper Zero collecting dust? Put it to work as an IR remote control emulator in Home Assistant!

![image](https://github.com/user-attachments/assets/73bc20ef-4634-4cd2-ac58-73bc60041641)

This integration allows you to use your Flipper Zero as a universal IR remote that can be controlled directly from Home Assistant. All you need to do is connect your Flipper Zero to the machine running Home Assistant via USB — no special setup required.

Easily send IR commands to TVs, air conditioners, and other IR-controlled devices from your smart home dashboard. Perfect for automation lovers and Flipper enthusiasts alike!

Features:
* Fully local control – no cloud required, no internet dependency.
* Fast and reliable – commands are sent instantly through USB.
* Plug and play – just connect your Flipper Zero via USB and you're good to go.
* Hot-plug support – you can safely disconnect and reconnect your Flipper Zero at any time. The integration will automatically re-establish the connection shortly after it's plugged back in.


## Integration setup

### Installation
####  Installation via HACS (Recommended)
The Home Assistant Community Store (HACS) is a powerful tool that allows you to discover and manage custom integrations and plugins. If you haven't installed HACS yet, refer to the official installation guide: https://www.hacs.xyz/docs/use/download/download/.

Just click on the button:

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=clusterm&repository=flipper_rc)

Or follow these steps:
* Navigate to HACS → Integrations in your Home Assistant sidebar.
* Click on the search icon and type "Flipper Zero Remote Control".
* Select the integration from the search results.
* Click Install.
* After installation, restart Home Assistant to load the new integration.
* Go to Settings → Devices & Services → Add Integration.
* Search for "Flipper Zero Remote Control" and follow the setup wizard.

#### Manual Installation
If you prefer manual installation or are not using HACS, follow these steps:
* Visit the [Releases](https://github.com/ClusterM/flipper_rc/releases) page of the integration's GitHub repository.
* Download the latest .zip file.
* Unzip the downloaded file.
* Locate the "flipper_rc" directory inside the extracted contents (in "custom_components" directory).
* Move the "flipper_rc" folder to your Home Assistant's custom_components directory.
* After copying the files, restart Home Assistant to recognize the new integration.
* Connect your Flipper to the machine running Home Assistant via USB.
* Make sure no applications are running and the desktop is visible.
* Navigate to Settings → Devices & Services → Add Integration.
* Search for "Flipper Zero Remote Control" and follow the setup wizard.

### Troubleshooting Serial Port Access on Linux
If your Flipper Zero is not detected or the integration fails to connect to the serial port, it's most likely due to permission issues or container isolation. Here’s how to fix it, depending on how Home Assistant is installed.

#### Home Assistant OS / Supervisor
*This is the official installation method, including Home Assistant OS and Supervised setups.*

Good news: Serial ports are automatically forwarded to Home Assistant if the device is properly detected by the host.

What to check:
* Go to Settings → System → Hardware
* Look for something like `/dev/ttyACM0`
* If it's there, Home Assistant should have access to it

If you don't see it:
* Make sure the device is properly connected
* Try reconnecting the device or restarting the host
* Check on the host system (ssh or console):
```
dmesg | grep tty
ls /dev/tty*
```

#### Home Assistant in Docker (manual)
*If you installed Home Assistant Core manually inside a Docker container.*

By default, Docker containers don’t have access to host devices. You must explicitly pass the serial port. How to fix:

Run Docker with:
```
--device /dev/ttyACM0
--group-add dialout
```
Full example:
```
docker run -d \
  --name homeassistant \
  --device /dev/ttyACM0 \
  --group-add dialout \
  -v /etc/localtime:/etc/localtime:ro \
  -v /PATH_TO_CONFIG:/config \
  --net=host \
  ghcr.io/home-assistant/home-assistant:stable
```
Make sure the port path matches your actual device (e.g., /dev/ttyACM0, etc.)

#### Home Assistant Core in virtualenv
*Installed with `pip` inside a Python virtual environment.*

This setup uses the current Linux user, so:
* Make sure that your user is in the `dialout` group (or `tty`, depending on distro):
```
sudo usermod -aG dialout $USER
```
* Reboot or log out and back in
* Check the port:
```
ls -l /dev/ttyACM0
```
You should see something like:
```
crw-rw---- 1 root dialout 166, 0 Apr 21 15:00 /dev/ttyACM0
```
The group (`dialout`) must match what your user has.


## How to use

This integration creates a new "remote.*" entity for your IR remote controller. But "Remote" entities are not directly controllable. You must use the `remote.send_command` service to send IR commands to your device and `remote.learn_command` service to learn new commands (read button codes from your remote). So, you can create scripts, automations, or even use the `remote.send_command` service directly from the Developer Tools to control your IR devices.

### Learn new commands (how to get button codes)

To learn new commands, call the `remote.learn_command` service and pass the entity_id of your remote controller. You can do it from the Developer Tools. You must specify a `command` parameter with the name of the command you want to learn. 
You can make integration to remember the button code by passing a `device` parameter. If you don't pass it, the button code will be shown in the notification only.

![image](https://github.com/user-attachments/assets/a11610c4-5c8d-4ded-a52d-acaf77c79fb1)

After calling the service, you will receive a notification which asks you to press the button on your real remote controller. Point your remote controller at the Flipper and press the button you want to learn. If the learning process is successful, you will receive a notification with the button code with some additional instructions.

![image](https://github.com/user-attachments/assets/3634347e-8f03-46eb-94cb-fabc5c1197a3)

This integration tries to decode the button code using different IR protocols. If it fails, you will receive a notification with the raw button code. See below for more information on how to format IR codes.

### Send commands

To send commands, call the `remote.send_command` service and pass the entity_id of your remote controller. You can use it in scripts and automations. Of course, you can try it from the Developer Tools as well. There are two methods to send commands: specifying a name of the previously learned command or passing a button code. To send a command by name, you must specify a `device` parameter with the name of the device you specified during learning:

```yaml
service: remote.send_command
data:
  entity_id: remote.flipper_zero_remote_control
  command: Power
  device: TV
```

To send a command by button code, just pass the `command` parameter with the button code:

```yaml
service: remote.send_command
data:
  entity_id: remote.flipper_zero_remote_control
  command: nec:addr=0xde,cmd=0xed
```


## IR Code Formatting

When defining IR commands, each code is represented as a single string. This string encodes the precise details of the IR command you want to send—either as a sequence of low-level raw timing values or by referencing a known IR protocol with corresponding parameters.

Because different devices and remotes may use various encoding schemes and timing, this flexible format ensures you can accurately represent a broad range of commands. Whether you’re dealing with a fully supported protocol like NEC or need to reproduce a custom signal captured from an unusual remote, these strings give you the necessary control and versatility.

Below are the two main formats you can use, along with details on how to specify parameters and numerical values.

### Raw Timing Format

The raw format allows you to directly specify the sequence of pulses and gaps as a list of timing values, measured in microseconds (or another timing unit depending on your configuration). This is useful when no known protocol fits your device, or if you have already captured the IR pattern and simply need to replay it.

```
raw:9000,4500,560,560,560,1690,560,1690,560
```

In this example, the comma-separated list of numbers represents the duration of each pulse or gap in the IR signal. The first number is the duration of the first pulse, the second number is the duration of the first gap, and so on. The values are in pairs, with the first number representing the pulse duration and the second number representing the gap duration.

### Protocol-Based Format

If your device uses a known IR protocol (like NEC, RC5, RC6, etc.), you can define the code using the protocol’s name followed by a series of key-value parameters. This approach is cleaner and more readable, and it leverages standard IR timing and data structures.

Example (NEC Protocol):
```
nec:addr=0x25,cmd=0x1E
```
Here, `addr` and `cmd` represent the address and command bytes defined by the NEC protocol. By using a recognized protocol, the integration takes care of the underlying timing details, making it easier to specify and understand the command.

For both raw and protocol-based formats, you can specify numeric values in either decimal or hexadecimal form. Hexadecimal values are prefixed with `0x`.

### Supported IR Protocols and Parameters

Below is a list of supported IR protocols with brief descriptions to help you choose the one suitable for your device.

#### NEC Protocols

- **nec**: The standard NEC protocol using a 32-bit code, widely used in consumer electronics. Requires parameters `addr` (address) and `cmd` (command).

- **nec-ext**: An extended version of the NEC protocol with a 32-bit code and a different structure for address and command. Also requires parameters `addr` and `cmd`.

- **nec42**: A 42-bit variant of the NEC protocol, providing a larger address range. Parameters: `addr` and `cmd`.

- **nec42-ext**: An extended version of the 42-bit NEC protocol for devices requiring additional address space. Requires `addr` and `cmd`.

#### RC Protocols

- **rc5**: The RC5 protocol is used in Philips devices and some other brands. Requires parameters `addr` and `cmd`, as well as an optional `toggle` parameter. RC5X is a variant of RC5 with a different toggle bit, it's supported and used for `cmd >= 64` (toggle bit is used as the 7th bit).

- **rc6**: An improved version of RC5, the RC6 protocol supports higher data transmission rates and more commands. Necessary parameters: `addr` and `cmd`. The `toggle` parameter is optional.

The `toggle` parameter can be 0 or 1 and is optional. It helps to distinguish between repeated commands. By default, the integration toggles the `toggle` parameter automatically.

#### Sony SIRC Protocols

- **sirc**: The standard Sony Infrared Remote Control (SIRC) protocol, usually using 12 bits. Requires `addr` and `cmd`.

- **sirc15**: The 15-bit variant of the SIRC protocol, providing more commands. Parameters: `addr` and `cmd`.

- **sirc20**: The 20-bit version of the SIRC protocol for devices with extended address and command space. Requires `addr` and `cmd`.

#### Other Protocols

- **samsung32**: Used in Samsung devices, this 32-bit protocol requires `addr` and `cmd`.

- **kaseikyo**: A complex protocol used by Panasonic and other companies, requires parameters `vendor_id`, `genre1`, `genre2`, `data`, and `id`.

- **rca**: The RCA protocol used in RCA brand devices. Requires `addr` and `cmd`.

- **pioneer**: Used in Pioneer devices, this protocol requires `addr` and `cmd`.

- **ac**: Some air conditioners use this protocol (at least Gorenie and MDV). Usually 16-bit command contains 4-bit mode, 4-bit fan speed, 4-bit temperature and some other bits. Requires `addr` and `cmd`.


## Donate

* [Become a sponsor on GitHub](https://github.com/sponsors/ClusterM)
* [Buy Me A Coffee](https://www.buymeacoffee.com/cluster)
* [Donation Alerts](https://www.donationalerts.com/r/clustermeerkat)
* [Boosty](https://boosty.to/cluster)
