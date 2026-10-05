#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_indigo_names_exist.py
# Description: Fail when plugin code names an `indigo` attribute that Indigo does not have,
#              e.g. indigo.kDimmerAction.TurnOn (no such enum) or indigo.kHvacMode.ProgramAuto
#              (no such value). Python only resolves these when the line runs, so the fault
#              hides until a user hits that path. Reads the source; imports nothing.
#              Generic: finds the bundle by glob, so it drops into any plugin repo unchanged.
# Author:      CliveS & Claude Opus 5.5
# Date:        05-10-2026
# Version:     1.0

import ast
import glob
import os

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Generated from the live Indigo 2025.2.0 module (API 3.8) on 05-10-2026 by
# IndigoConformance/capture/surface.py. Regenerate when Indigo is upgraded.
INDIGO_TOP_LEVEL = frozenset(['ActionGroup', 'ActionGroupCmds', 'ActionGroupIter', 'ActionGroupList', 'BaseAction',
 'BaseElem', 'BdbQuit', 'CallbackCompleteHandler', 'ControlPage', 'ControlPageCmds',
 'ControlPageIter', 'ControlPageList', 'Device', 'DeviceAction', 'DeviceCmds', 'DeviceIter',
 'DeviceList', 'DeviceStateChangeTrigger', 'DeviceSubTypes', 'Dict', 'DimmerDevice',
 'DimmerDeviceCmds', 'DimmerDeviceSubTypes', 'DimmerRelayAction', 'EmailReceivedTrigger',
 'Event', 'EventScheduleCmds', 'EventTriggerCmds', 'Folder', 'FolderCmds', 'FolderIter',
 'FolderList', 'GeneralDeviceAction', 'HostInfo', 'InsteonCmd', 'InsteonCmdInterface',
 'InsteonCommandReceivedTrigger', 'InterfaceFailureTrigger', 'InterfaceInitializedTrigger',
 'List', 'MultiIODevice', 'MultiIODeviceCmds', 'PluginAction', 'PluginBase',
 'PluginEventTrigger', 'PluginInfo', 'PowerFailureTrigger', 'RelayDevice', 'RelayDeviceCmds',
 'RelayDeviceSubTypes', 'Schedule', 'ScheduleIter', 'ScheduleList', 'SensorAction',
 'SensorDevice', 'SensorDeviceCmds', 'SensorDeviceSubTypes', 'ServerInfo',
 'ServerShutdownTrigger', 'ServerStartupTrigger', 'SpeedControlAction', 'SpeedControlDevice',
 'SpeedControlDeviceCmds', 'SprinklerAction', 'SprinklerDevice', 'SprinklerDeviceCmds',
 'ThermostatAction', 'ThermostatDevice', 'ThermostatDeviceCmds', 'Trigger',
 'TriggerDevStateChangeCmds', 'TriggerEmailRcvdCmds', 'TriggerInstnCmdRcvdCmds',
 'TriggerInterfaceFailedCmds', 'TriggerInterfaceInitedCmds', 'TriggerIter', 'TriggerList',
 'TriggerPluginEventCmds', 'TriggerPowerFailureCmds', 'TriggerServerShutdownCmds',
 'TriggerServerStartupCmds', 'TriggerVarValChangeCmds', 'TriggerX10CmdRcvdCmds',
 'UniversalAction', 'Variable', 'VariableCmds', 'VariableIter', 'VariableList',
 'VariableValueChangeTrigger', 'X10Cmd', 'X10CmdInterface', 'X10CommandReceivedTrigger',
 'ZWaveInterface', 'acquireCallbackCompleteHandler', 'actionGroup', 'actionGroups',
 'activePlugin', 'controlPage', 'controlPages', 'debugger', 'devStateChange', 'device',
 'devices', 'dimmer', 'emailRcvd', 'host', 'importlib', 'indigo', 'insteon', 'insteonCmdRcvd',
 'interfaceFail', 'interfaceInit', 'iodevice', 'kAllDeviceSel', 'kDateType',
 'kDeprecatedTypeId', 'kDeviceAction', 'kDeviceGeneralAction', 'kDeviceSourceType',
 'kDeviceSubType', 'kDimmerDeviceSubType', 'kDimmerRelayAction', 'kElemTypeId', 'kEmailFilter',
 'kFanMode', 'kHvacMode', 'kInsteonCmd', 'kInterface', 'kLicenseStatus',
 'kPluginDebugMode_debugPdb', 'kPluginDebugMode_debugPudb', 'kPluginDebugMode_debugPyCharm',
 'kPluginDebugMode_none', 'kProgressDescType', 'kProtocol', 'kPyCharmDebugServerIP',
 'kPyCharmDebugServerPort', 'kRelayDeviceSubType', 'kSensorAction', 'kSensorDeviceSubType',
 'kSpeedControlAction', 'kSprinklerAction', 'kStateChange', 'kStateImageSel',
 'kSubAtomicTypeId', 'kThermostatAction', 'kTimeType', 'kTriggerKeyType', 'kUniversalAction',
 'kVarChange', 'kX10AvButton', 'kX10Cmd', 'pluginEvent', 'powerFail', 'rawServerCommand',
 'rawServerCommandPacketXml', 'rawServerRequest', 'rawServerRequestPacketXml', 'relay',
 'schedule', 'schedules', 'script', 'sensor', 'server', 'serverShutdown', 'serverStartup',
 'signal', 'signal_handler', 'socket', 'speedcontrol', 'sprinkler', 'sys', 'thermostat',
 'traceback', 'trigger', 'triggers', 'utils', 'varValueChange', 'variable', 'variables', 'x10',
 'x10CmdRcvd', 'zwave'])

INDIGO_ENUMS = {
    'kAllDeviceSel': frozenset(['All', 'HouseCodeA', 'HouseCodeB', 'HouseCodeC', 'HouseCodeD', 'HouseCodeE',
         'HouseCodeF', 'HouseCodeG', 'HouseCodeH', 'HouseCodeI', 'HouseCodeJ',
         'HouseCodeK', 'HouseCodeL', 'HouseCodeM', 'HouseCodeN', 'HouseCodeO',
         'HouseCodeP', 'Insteon', 'X10', 'ZWave']),
    'kDateType': frozenset(['Absolute', 'DaysOfMonth', 'DaysOfMonthInterval', 'DaysOfWeek', 'EveryDay']),
    'kDeprecatedTypeId': frozenset(['ExecuteEmbeddedAppleScript', 'ExecuteLinkedAppleScript']),
    'kDeviceAction': frozenset(['AllLightsOff', 'AllLightsOn', 'AllOff', 'BrightenBy', 'Close', 'DimBy',
         'Lock', 'Open', 'RequestStatus', 'SetBrightness', 'SetColorLevels', 'Toggle',
         'TurnOff', 'TurnOn', 'Unlock']),
    'kDeviceGeneralAction': frozenset(['Beep', 'EnergyReset', 'EnergyUpdate', 'RequestStatus']),
    'kDeviceSourceType': frozenset(['AnyDevice', 'DeviceId', 'NoDevice', 'RawAddress']),
    'kDeviceSubType': frozenset(['AlarmSystem', 'Amplifier', 'Automobile', 'Camera', 'Keypad', 'Mobile',
         'Other', 'Remote', 'Robot', 'Security', 'Speaker', 'Streaming', 'Television',
         'Weather']),
    'kDimmerDeviceSubType': frozenset(['Blind', 'Bulb', 'ColorBulb', 'ColorDimmer', 'Dimmer', 'Fan', 'InLine',
         'Outlet', 'PlugIn', 'Valve']),
    'kDimmerRelayAction': frozenset(['AllLightsOff', 'AllLightsOn', 'AllOff', 'BrightenBy', 'DimBy',
         'SetBrightness', 'SetColorLevels', 'Toggle', 'TurnOff', 'TurnOn']),
    'kElemTypeId': frozenset(['ActionGroup', 'ControlPage', 'Device', 'DeviceGroup', 'Schedule', 'Trigger',
         'Variable']),
    'kEmailFilter': frozenset(['AnyEmail', 'MatchEmailFields']),
    'kFanMode': frozenset(['AlwaysOn', 'Auto']),
    'kHvacMode': frozenset(['Cool', 'Heat', 'HeatCool', 'Off', 'ProgramCool', 'ProgramHeat',
         'ProgramHeatCool']),
    'kInsteonCmd': frozenset(['AllBrighten', 'AllDim', 'AllInstantOff', 'AllInstantOn', 'AllOff', 'AllOn',
         'AnyCommand', 'Brighten', 'Dim', 'InstantOff', 'InstantOn', 'Off', 'On',
         'StatusChanged']),
    'kInterface': frozenset(['All', 'InsteonX10', 'Plugin', 'X10RF']),
    'kLicenseStatus': frozenset(['ActiveSubscription', 'ActiveTrial', 'ExpiredSubscription', 'Unknown']),
    'kProgressDescType': frozenset(['Executed', 'Executed_fail', 'Generic', 'Generic_fail', 'Processed',
         'Processed_fail', 'Received', 'Received_fail', 'Sent', 'Sent_fail', 'Unused']),
    'kProtocol': frozenset(['Insteon', 'Plugin', 'X10', 'ZWave']),
    'kRelayDeviceSubType': frozenset(['DoorBell', 'DoorController', 'GarageController', 'InLine', 'Lock', 'Outlet',
         'PlugIn', 'Siren', 'Switch']),
    'kSensorAction': frozenset(['RequestStatus', 'Toggle', 'TurnOff', 'TurnOn']),
    'kSensorDeviceSubType': frozenset(['Analog', 'Binary', 'CO', 'DoorWindow', 'GasLeak', 'GlassBreak', 'Humidity',
         'Illuminance', 'Motion', 'Presence', 'Pressure', 'Smoke', 'Tamper',
         'Temperature', 'UV', 'Vibration', 'Voltage', 'WaterLeak', 'Zone']),
    'kSpeedControlAction': frozenset(['DecreaseSpeedIndex', 'IncreaseSpeedIndex', 'RequestStatus', 'SetSpeedIndex',
         'SetSpeedLevel', 'Toggle', 'TurnOff', 'TurnOn']),
    'kSprinklerAction': frozenset(['AllZonesOff', 'NextZone', 'PauseSchedule', 'PreviousZone', 'RequestStatusAll',
         'ResumeSchedule', 'RunNewSchedule', 'RunPreviousSchedule', 'StopSchedule',
         'ZoneOn']),
    'kStateChange': frozenset(['BecomesEqual', 'BecomesFalse', 'BecomesGreaterThan', 'BecomesLessThan',
         'BecomesNotEqual', 'BecomesTrue', 'Changes']),
    'kStateImageSel': frozenset(['Auto', 'AvPaused', 'AvPlaying', 'AvStopped', 'BatteryCharger',
         'BatteryChargerOn', 'BatteryLevel', 'BatteryLevel25', 'BatteryLevel50',
         'BatteryLevel75', 'BatteryLevelHigh', 'BatteryLevelLow', 'Closed', 'Custom',
         'DehumidifierOff', 'DehumidifierOn', 'DimmerOff', 'DimmerOn',
         'DoorSensorClosed', 'DoorSensorOpened', 'EnergyMeterOff', 'EnergyMeterOn',
         'Error', 'FanHigh', 'FanLow', 'FanMedium', 'FanOff', 'HumidifierOff',
         'HumidifierOn', 'HumiditySensor', 'HumiditySensorOn', 'HvacAutoMode',
         'HvacCoolMode', 'HvacCooling', 'HvacFanOn', 'HvacHeatMode', 'HvacHeating',
         'HvacOff', 'LightSensor', 'LightSensorOn', 'Locked', 'MotionSensor',
         'MotionSensorTripped', 'NoImage', 'Opened', 'PowerOff', 'PowerOn', 'SensorOff',
         'SensorOn', 'SensorTripped', 'SprinklerOff', 'SprinklerOn',
         'TemperatureSensor', 'TemperatureSensorOn', 'TimerOff', 'TimerOn', 'Unlocked',
         'WindDirectionSensor', 'WindDirectionSensorEast', 'WindDirectionSensorNorth',
         'WindDirectionSensorNorthEast', 'WindDirectionSensorNorthWest',
         'WindDirectionSensorSouth', 'WindDirectionSensorSouthEast',
         'WindDirectionSensorSouthWest', 'WindDirectionSensorWest', 'WindSpeedSensor',
         'WindSpeedSensorHigh', 'WindSpeedSensorLow', 'WindSpeedSensorMedium',
         'WindowSensorClosed', 'WindowSensorOpened']),
    'kSubAtomicTypeId': frozenset(['Action', 'Condition', 'Control', 'Device', 'Schedule', 'Trigger']),
    'kThermostatAction': frozenset(['DecreaseCoolSetpoint', 'DecreaseHeatSetpoint', 'IncreaseCoolSetpoint',
         'IncreaseHeatSetpoint', 'RequestDeadbands', 'RequestEquipmentState',
         'RequestHumidities', 'RequestMode', 'RequestSetpoints', 'RequestStatusAll',
         'RequestTemperatures', 'SetCoolSetpoint', 'SetFanMode', 'SetHeatSetpoint',
         'SetHvacMode']),
    'kTimeType': frozenset(['Absolute', 'Countdown', 'Sunrise', 'Sunset']),
    'kTriggerKeyType': frozenset(['BoolOnOff', 'BoolOneZero', 'BoolTrueFalse', 'BoolYesNo', 'Compound',
         'Enumeration', 'Integer', 'Label', 'Number', 'Real', 'String']),
    'kUniversalAction': frozenset(['Beep', 'EnergyReset', 'EnergyUpdate', 'RequestStatus']),
    'kVarChange': frozenset(['BecomesEqual', 'BecomesFalse', 'BecomesGreaterThan', 'BecomesLessThan',
         'BecomesNotEqual', 'BecomesTrue', 'Changes']),
    'kX10AvButton': frozenset(['0', '1', '2', '3', '4', '5', '6', '7', '8', '9', 'AB', 'ChannelDown',
         'ChannelUp', 'Display', 'Down', 'Enter', 'Exit', 'Forward', 'Left', 'Menu',
         'Mute', 'PC', 'Pause', 'Play', 'Power', 'Recall', 'Record', 'Return', 'Rewind',
         'Right', 'Stop', 'Title', 'Up', 'VolumeDown', 'VolumeUp']),
    'kX10Cmd': frozenset(['AllLightsOff', 'AllLightsOn', 'AllOff', 'AnyCommand', 'AvButtonPressed',
         'Brighten', 'Dim', 'ExtendedData', 'Off', 'On', 'PresetDim',
         'StatusOffResponse', 'StatusOnResponse']),
}

def _sources():
    for bundle in glob.glob(os.path.join(REPO, "*.indigoPlugin")):
        root = os.path.join(bundle, "Contents", "Server Plugin")
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in ("Packages", "__pycache__")]
            for f in filenames:
                if f.endswith(".py"):
                    yield os.path.join(dirpath, f)


def _indigo_chains(path):
    with open(path, encoding="utf-8") as fh:
        tree = ast.parse(fh.read(), filename=path)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Attribute):
            continue
        parts, cur = [], node
        while isinstance(cur, ast.Attribute):
            parts.append(cur.attr)
            cur = cur.value
        if isinstance(cur, ast.Name) and cur.id == "indigo":
            yield node.lineno, list(reversed(parts))


def find_unknown_names():
    bad = set()
    for path in _sources():
        rel = os.path.relpath(path, REPO)
        for lineno, parts in _indigo_chains(path):
            top = parts[0]
            if top.startswith("__"):
                continue
            if top not in INDIGO_TOP_LEVEL:
                bad.add(f"{rel}:{lineno}: indigo.{top} does not exist")
            elif top in INDIGO_ENUMS and len(parts) > 1 and parts[1] not in INDIGO_ENUMS[top] \
                    and not parts[1].startswith("_"):
                bad.add(f"{rel}:{lineno}: indigo.{top}.{parts[1]} does not exist")
    return sorted(bad)


def test_every_indigo_name_the_plugin_uses_exists():
    bad = find_unknown_names()
    assert not bad, "Names Indigo 2025.2 does not have:\n" + "\n".join(bad)


def test_the_check_can_fail(tmp_path):
    """The guard must be able to see the fault it exists for."""
    src = tmp_path / "probe.py"
    src.write_text("import indigo\nx = indigo.kDimmerAction.TurnOn\n"
                   "y = indigo.kHvacMode.ProgramAuto\nz = indigo.kHvacMode.Heat\n")
    found = [p for _, p in _indigo_chains(str(src))]
    assert ["kDimmerAction", "TurnOn"] in found
    assert "kDimmerAction" not in INDIGO_TOP_LEVEL
    assert "ProgramAuto" not in INDIGO_ENUMS["kHvacMode"]
    assert "Heat" in INDIGO_ENUMS["kHvacMode"]
