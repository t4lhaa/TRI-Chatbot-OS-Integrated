
CXX      = g++
CXXFLAGS = -std=c++17 -pthread -Wall -O2
TARGET   = kernel_server
SRC      = kernel/kernel_server.cpp
HEADERS  = kernel/page_table.h  kernel/pcb.h       kernel/vector_db.h \
           kernel/scheduler.h   kernel/syscall.h    kernel/semaphore.h

all: $(TARGET)

$(TARGET): $(SRC) $(HEADERS)
	$(CXX) $(CXXFLAGS) -I. -o $(TARGET) $(SRC)
	@echo "Build OK → ./$(TARGET)"

run: all
	./$(TARGET) --policy LRU --quantum 500

run-fifo: all
	./$(TARGET) --policy FIFO --quantum 500

run-clock: all
	./$(TARGET) --policy CLOCK --quantum 500

run-lfu: all
	./$(TARGET) --policy LFU --quantum 500

clean:
	rm -f $(TARGET)
