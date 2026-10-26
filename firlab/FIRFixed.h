// Runtime para filtros FIR exportados por FIR Fixed Lab.
// Todas las entradas y salidas de process() son enteros raw, no float.
#pragma once

#include <stdint.h>

#ifdef ARDUINO
#include <Arduino.h>
#include <avr/pgmspace.h>
#else
#define PROGMEM
#endif

enum FirRounding : uint8_t {
  FIR_ROUND_FLOOR,
  FIR_ROUND_CEIL,
  FIR_ROUND_TOWARD_ZERO,
  FIR_ROUND_NEAREST,       // Empates alejándose de cero.
  FIR_ROUND_CONVERGENT     // Empates al entero par.
};

enum FirOverflow : uint8_t { FIR_OVERFLOW_SATURATE, FIR_OVERFLOW_WRAP };

struct FirFormat {
  uint8_t wordLength;      // Incluye el signo cuando signedValue es true.
  uint8_t fractionLength;  // Bits a la derecha del punto binario.
  bool signedValue;
};

struct FirConfig {
  const int32_t *coefficients;  // Valores raw, almacenados en PROGMEM.
  uint16_t taps;
  FirFormat inputFormat;
  FirFormat coefficientFormat;
  FirFormat productFormat;
  FirFormat accumulatorFormat;
  FirFormat outputFormat;
  FirRounding rounding;
  FirOverflow overflow;
};

class FirFixed {
 public:
  FirFixed(const FirConfig &config, int32_t *delayLine)
      : config_(config), delayLine_(delayLine), writeIndex_(0) { reset(); }

  void reset() {
    for (uint16_t i = 0; i < config_.taps; ++i) delayLine_[i] = 0;
    writeIndex_ = 0;
  }

  // inputRaw usa config_.inputFormat; el retorno usa config_.outputFormat.
  int32_t process(int32_t inputRaw) {
    const int64_t x = applyOverflow(inputRaw, config_.inputFormat, config_.overflow);
    delayLine_[writeIndex_] = static_cast<int32_t>(x);
    int64_t accumulator = 0;
    uint16_t stateIndex = writeIndex_;
    for (uint16_t k = 0; k < config_.taps; ++k) {
      const int64_t coefficient = readCoefficient(k);
      int64_t product = static_cast<int64_t>(delayLine_[stateIndex]) * coefficient;
      product = rescale(product,
                        config_.inputFormat.fractionLength + config_.coefficientFormat.fractionLength,
                        config_.productFormat);
      const int64_t alignedProduct = rescale(product, config_.productFormat.fractionLength,
                                             config_.accumulatorFormat);
      accumulator = applyOverflow(accumulator + alignedProduct, config_.accumulatorFormat,
                                  config_.overflow);
      stateIndex = stateIndex == 0 ? config_.taps - 1 : stateIndex - 1;
    }
    writeIndex_ = writeIndex_ + 1 == config_.taps ? 0 : writeIndex_ + 1;
    return static_cast<int32_t>(rescale(accumulator, config_.accumulatorFormat.fractionLength,
                                        config_.outputFormat));
  }

 private:
  const FirConfig &config_;
  int32_t *delayLine_;
  uint16_t writeIndex_;

  int64_t readCoefficient(uint16_t index) const {
#ifdef __AVR__
    return static_cast<int32_t>(pgm_read_dword(config_.coefficients + index));
#else
    return config_.coefficients[index];
#endif
  }

  static int64_t minimum(const FirFormat &format) {
    return format.signedValue ? -(int64_t(1) << (format.wordLength - 1)) : 0;
  }

  static int64_t maximum(const FirFormat &format) {
    return format.signedValue ? (int64_t(1) << (format.wordLength - 1)) - 1
                              : (int64_t(1) << format.wordLength) - 1;
  }

  static int64_t applyOverflow(int64_t value, const FirFormat &format, FirOverflow overflow) {
    if (value >= minimum(format) && value <= maximum(format)) return value;
    if (overflow == FIR_OVERFLOW_SATURATE) {
      return value < minimum(format) ? minimum(format) : maximum(format);
    }
    const uint64_t modulus = uint64_t(1) << format.wordLength;
    uint64_t wrapped = static_cast<uint64_t>(value) & (modulus - 1);
    if (format.signedValue && wrapped >= (uint64_t(1) << (format.wordLength - 1))) {
      return static_cast<int64_t>(wrapped) - static_cast<int64_t>(modulus);
    }
    return static_cast<int64_t>(wrapped);
  }

  static int64_t shiftRight(int64_t value, uint8_t shift, FirRounding rounding) {
    if (shift == 0) return value;
    const int64_t divisor = int64_t(1) << shift;
    const int64_t magnitude = value < 0 ? -value : value;
    const int64_t quotient = magnitude / divisor;
    const int64_t remainder = magnitude % divisor;
    int64_t rounded = quotient;
    if (rounding == FIR_ROUND_FLOOR) {
      return value < 0 && remainder ? -(quotient + 1) : (value < 0 ? -quotient : quotient);
    }
    if (rounding == FIR_ROUND_CEIL) {
      return value > 0 && remainder ? quotient + 1 : (value < 0 ? -quotient : quotient);
    }
    if (rounding == FIR_ROUND_NEAREST || rounding == FIR_ROUND_CONVERGENT) {
      const int64_t twice = remainder * 2;
      if (twice > divisor || (twice == divisor &&
          (rounding == FIR_ROUND_NEAREST || (quotient & 1)))) ++rounded;
    }
    return value < 0 ? -rounded : rounded;
  }

  int64_t rescale(int64_t raw, uint8_t sourceFractionLength, const FirFormat &destination) const {
    if (sourceFractionLength < destination.fractionLength) {
      raw <<= (destination.fractionLength - sourceFractionLength);
    } else {
      raw = shiftRight(raw, sourceFractionLength - destination.fractionLength, config_.rounding);
    }
    return applyOverflow(raw, destination, config_.overflow);
  }
};
