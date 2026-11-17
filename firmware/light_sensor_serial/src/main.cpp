#include <Arduino.h>
#include <Wire.h>
#include <math.h>

// Standard ESP32 DevKit I2C pins; BH1750 is probed at both legal addresses.
static constexpr int SDA_PIN = 21;
static constexpr int SCL_PIN = 22;
static uint8_t sensorAddress = 0;
static unsigned long lastRetryMs = 0;

static bool probe(uint8_t address) {
  Wire.beginTransmission(address);
  return Wire.endTransmission() == 0;
}

static bool initializeSensor() {
  if (probe(0x23)) sensorAddress = 0x23;
  else if (probe(0x5C)) sensorAddress = 0x5C;
  else return false;

  Wire.beginTransmission(sensorAddress);
  Wire.write(0x10);  // continuous high-resolution measurement mode
  if (Wire.endTransmission() != 0) {
    sensorAddress = 0;
    return false;
  }
  delay(180);
  Serial.printf("BH1750 ready at 0x%02X on SDA=%d SCL=%d\n", sensorAddress, SDA_PIN, SCL_PIN);
  return true;
}

void setup() {
  Serial.begin(9600);
  delay(300);
  Wire.begin(SDA_PIN, SCL_PIN, 100000);
  Serial.println("BH1750 serial-only firmware starting");
  initializeSensor();
}

void loop() {
  if (sensorAddress == 0) {
    if (millis() - lastRetryMs >= 3000) {
      lastRetryMs = millis();
      Serial.println("BH1750 not detected on GPIO21/22; check I2C wiring");
      initializeSensor();
    }
    delay(50);
    return;
  }

  Wire.requestFrom(sensorAddress, (uint8_t)2);
  if (Wire.available() >= 2) {
    const uint16_t raw = (static_cast<uint16_t>(Wire.read()) << 8) | Wire.read();
    const float lux = raw / 1.2f;
    if (isfinite(lux) && lux >= 0.0f && lux <= 120000.0f) {
      Serial.printf("Light: %.2f lx\n", lux);
    } else {
      Serial.println("BH1750 returned an invalid value");
    }
  } else {
    Serial.println("BH1750 read failed");
  }
  delay(1000);
}
