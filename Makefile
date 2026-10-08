

all: clean
	python3 main.py --gui

clean:
	rm -rf ./output
	