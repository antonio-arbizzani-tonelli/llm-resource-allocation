CXX = g++
CPPFLAGS = -Iinclude
WARNINGS = -Wall -Wextra -Wpedantic
COMMON = -std=c++20 $(WARNINGS) -ffp-contract=off
MODE ?= release
BUILD = build/$(MODE)
ifeq ($(MODE),debug)
CXXFLAGS = $(COMMON) -O0 -g
else ifeq ($(MODE),profile)
CXXFLAGS = $(COMMON) -O2 -g -pg
LDFLAGS = -pg
else ifeq ($(MODE),sanitize)
CXXFLAGS = $(COMMON) -O1 -g -fsanitize=address,undefined -fno-omit-frame-pointer
LDFLAGS = -fsanitize=address,undefined
else
CXXFLAGS = $(COMMON) -O2 -g
endif
SOURCES = src/core.cpp src/gh.cpp src/agh.cpp
OBJECTS = $(SOURCES:src/%.cpp=$(BUILD)/%.o)
OPENMP = -fopenmp
PYTHON ?= python3
# The experimental generator rejects changes to the accepted scientific source.
PROBE_CORE_SHA256 = d49d16ebbf0d725c64d876c36369bc1db77591d943ffd516c85f8b0b4edab036
.PHONY: all test openmp campaign-test validation-probe validation-probe-test clean
all: $(BUILD)/pacs_serial
$(BUILD)/%.o: src/%.cpp
	@mkdir -p $(BUILD)
	$(CXX) $(CPPFLAGS) $(CXXFLAGS) -MMD -MP -c $< -o $@
$(BUILD)/pacs_serial: $(OBJECTS) $(BUILD)/io.o $(BUILD)/main.o
	$(CXX) $^ $(LDFLAGS) -o $@
$(BUILD)/core_tests: $(OBJECTS) tests/core_tests.cpp tests/gh_tests.cpp tests/agh_tests.cpp
	$(CXX) $(CPPFLAGS) $(CXXFLAGS) $^ $(LDFLAGS) -o $@
test: $(BUILD)/core_tests
	$(BUILD)/core_tests
$(BUILD)/campaign.o $(BUILD)/campaign_main.o: $(BUILD)/%.o: src/%.cpp
	@mkdir -p $(BUILD)
	$(CXX) $(CPPFLAGS) $(CXXFLAGS) $(OPENMP) -MMD -MP -c $< -o $@
$(BUILD)/pacs_campaign: $(OBJECTS) $(BUILD)/io.o $(BUILD)/campaign.o $(BUILD)/campaign_main.o
	$(CXX) $^ $(LDFLAGS) $(OPENMP) -o $@
$(BUILD)/campaign_tests: $(OBJECTS) $(BUILD)/io.o $(BUILD)/campaign.o tests/campaign_tests.cpp
	$(CXX) $(CPPFLAGS) $(CXXFLAGS) $^ $(LDFLAGS) $(OPENMP) -o $@
openmp: $(BUILD)/pacs_campaign
campaign-test: $(BUILD)/campaign_tests
	$(BUILD)/campaign_tests
$(BUILD)/probe_core.cpp: src/core.cpp experiments/generate_validation_core.py
	@mkdir -p $(BUILD)
	$(PYTHON) experiments/generate_validation_core.py --source $< --output $@ --expected-source-sha256 $(PROBE_CORE_SHA256)
$(BUILD)/probe_core.o: $(BUILD)/probe_core.cpp experiments/validation_probe.hpp
	$(CXX) $(CPPFLAGS) -Iexperiments $(CXXFLAGS) $(OPENMP) -MMD -MP -c $< -o $@
$(BUILD)/validation_probe.o $(BUILD)/validation_probe_main.o: $(BUILD)/%.o: experiments/%.cpp
	@mkdir -p $(BUILD)
	$(CXX) $(CPPFLAGS) -Iexperiments $(CXXFLAGS) $(OPENMP) -MMD -MP -c $< -o $@
$(BUILD)/pacs_validation_probe: $(BUILD)/probe_core.o $(BUILD)/validation_probe.o $(BUILD)/gh.o $(BUILD)/agh.o $(BUILD)/io.o $(BUILD)/validation_probe_main.o
	$(CXX) $^ $(LDFLAGS) $(OPENMP) -o $@
$(BUILD)/validation_probe_tests: $(BUILD)/probe_core.o $(BUILD)/validation_probe.o experiments/validation_probe_tests.cpp
	$(CXX) $(CPPFLAGS) -Iexperiments $(CXXFLAGS) $^ $(LDFLAGS) $(OPENMP) -o $@
validation-probe: $(BUILD)/pacs_validation_probe
validation-probe-test: $(BUILD)/validation_probe_tests
	$(BUILD)/validation_probe_tests
clean:
	rm -rf build
-include $(OBJECTS:.o=.d) $(BUILD)/main.d $(BUILD)/io.d $(BUILD)/campaign.d $(BUILD)/campaign_main.d
-include $(BUILD)/probe_core.d $(BUILD)/validation_probe.d $(BUILD)/validation_probe_main.d
