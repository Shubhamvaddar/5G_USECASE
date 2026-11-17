#include <Arduino.h>
#include <Wire.h>
#include <math.h>

static constexpr int SDA_PIN = 21;
static constexpr int SCL_PIN = 22;
static uint8_t sensorAddress = 0;
static unsigned long lastRetryMs = 0;

static bool probe(uint8_t address) {
  Wire.beginTransmission(address);
  return Wire.endTransmission() == 0;
}

static bool initializeSensor() {
  sensorAddress = probe(0x23) ? 0x23 : (probe(0x5C) ? 0x5C : 0);
  if (!sensorAddress) return false;

  Wire.beginTransmission(sensorAddress);
  Wire.write(0x01);  // power on
  if (Wire.endTransmission() != 0) {
    sensorAddress = 0;
    return false;
  }
  delay(10);
  Wire.beginTransmission(sensorAddress);
  Wire.write(0x07);  // reset data register
  const bool ok = Wire.endTransmission() == 0;
  delay(10);
  if (!ok) {
    sensorAddress = 0;
    return false;
  }
  Serial.printf("BH1750 ready at 0x%02X on SDA=%d SCL=%d; one-shot mode\n", sensorAddress, SDA_PIN, SCL_PIN);
  return true;
}

void setup() {
  Serial.begin(9600);
  delay(300);
  Wire.begin(SDA_PIN, SCL_PIN, 100000);
  Serial.println("BH1750 serial-only diagnostic firmware starting");
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

  // One-time high-resolution conversion; BH1750 powers down after each result.
  Wire.beginTransmission(sensorAddress);
  Wire.write(0x20);
  if (Wire.endTransmission() != 0) {
    Serial.println("BH1750 measurement command failed");
    delay(1000);
    return;
  }
  delay(180);  // maximum high-resolution conversion time

  const size_t received = Wire.requestFrom(sensorAddress, static_cast<uint8_t>(2));
  if (received >= 2 && Wire.available() >= 2) {
    const uint16_t raw = (static_cast<uint16_t>(Wire.read()) << 8) | Wire.read();
    const float lux = raw / 1.2f;
    if (isfinite(lux) && lux >= 0.0f && lux <= 120000.0f) {
      Serial.printf("Light: %.2f lx (raw=%u)\n", lux, raw);
    } else {
      Serial.printf("BH1750 invalid value (raw=%u)\n", raw);
    }
  } else {
    while (Wire.available()) Wire.read();
    Serial.println("BH1750 read failed");
  }
  delay(820);
}
