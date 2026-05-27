import time

with open('flush.txt', 'w') as file:
    file.write('This is the flush file.\n')
    time.sleep(2)
    file.write('Flushing complete.\n')
    file.flush()