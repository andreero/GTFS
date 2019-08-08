import csv
import argparse
from datetime import datetime
from collections import namedtuple

TIMEZONE = 'Europe/Zagreb'
new_schedule_columns = ['id_ulaz', 'id_izlaz', 'polazak', 'dolazak', 'cijena', 'prijevoznik', 'broj_segmenata']
new_stops_columns = ["rowNumber", "marketing_carrier_code", "place_code", "stop_id", "stop_code", "stop_name",
                     "stop_desc", "stop_lat", "stop_lon", "stop_timezone"]


def convert_time(old_time):
    old_format = '%Y-%m-%d %H:%M:%S %z'
    new_format = '%b  %d %Y  %I:%M%p'
    time = datetime.strptime(old_time, old_format)
    new_time = datetime.strftime(time, new_format)
    return new_time


def convert_agency(agency):
    if agency == "GLOB":
        return "Globtour"


def convert_stops(stops_file):
    with stops_file as infile, open('new_stops.csv', 'w', newline='\n', encoding='utf-8') as outfile:
        reader = csv.reader(infile, dialect='excel')
        writer = csv.writer(outfile)

        old_headers = next(reader, None)
        old_headers[0] = old_headers[0].replace(u'\ufeff', '')  # remove byte-order-mark, if present
        new_headers = new_stops_columns
        writer.writerow(new_headers)

        old_stop = namedtuple("Old_stop", old_headers)
        new_stop = namedtuple("New_stop", new_headers)

        for i, row in enumerate(reader):
            old_record = old_stop(*row)
            new_record = new_stop(
                rowNumber=i,
                marketing_carrier_code=old_record.code,
                place_code=old_record.placecode_code,
                stop_id=old_record.station_code,
                stop_code=old_record.station_code,
                stop_name=old_record.station_name,
                stop_desc=old_record.description,
                stop_lat=old_record.latitude,
                stop_lon=old_record.longitude,
                stop_timezone='',
            )
            writer.writerow(list(new_record))



def convert_schedule(schedule_file):
    with schedule_file as infile, open('new_schedule.csv', 'w', newline='\n', encoding='utf-8') as outfile:
        reader = csv.reader(infile, dialect='excel', delimiter=';')
        writer = csv.writer(outfile, dialect='excel', delimiter=';')

        old_headers = next(reader, None)
        old_headers[0] = old_headers[0].replace(u'\ufeff', '')  # remove byte-order-mark, if present
        new_headers = new_schedule_columns
        writer.writerow(new_headers)

        old_schedule = namedtuple("Old_schedule", old_headers)
        new_schedule = namedtuple("New_schedule", new_headers)

        for i, row in enumerate(reader):
            old_record = old_schedule(*row)
            new_record = new_schedule(
                id_ulaz=old_record.departure_station,
                id_izlaz=old_record.arrival_station,
                polazak=convert_time(old_record.departure_time),
                dolazak=convert_time(old_record.arrival_time),
                cijena=old_record.price,
                prijevoznik=convert_agency(old_record.carrier),
                broj_segmenata=old_record.segments,
            )
            writer.writerow(list(new_record))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('input_stops', type=argparse.FileType('r'))
    parser.add_argument('input_schedule', type=argparse.FileType('r'))
    options = parser.parse_args()

    convert_stops(options.input_stops)
    convert_schedule(options.input_schedule)


if __name__ == "__main__":
    main()
