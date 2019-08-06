from collections import namedtuple, defaultdict
from datetime import datetime
import os
import csv
import zipfile
import argparse

DEFAULT_STOPS_FILE = 'stops.csv'
DEFAULT_SCHEDULE_FILE = 'Schedule.csv'
DEFAULT_OUTPUT_FILE = 'GTFS_output.zip'
DEFAULT_MAX_SEGMENTS = 1

AGENCIES = {
    'Autopromet d.d. Slunj': {
        'code': 'ASLU',
        'url': 'http://www.autopromet.hr/',
         },
    'Autotrans d.d.': {
        'code': 'AUTT',
        'url': 'https://vollo.hr/autobus/prijevoznik/autotrans',
        },
    'App d.d. Požega': {
        'code': 'APOE',
        'url': 'https://www.putovnica.net/prijevoz/app-pozega',
        },
    'Panturist d.d. Osijek': {
        'code': 'PANT',
        'url': 'http://panturist-turizam.hr/',
    },
}

ROUTE_TYPE = 3  # Bus
PAYMENT_METHOD = 1  # paid before boarding
TIMEZONE = 'Europe/Zagreb'
CURRENCY_TYPE = 'EUR'

Agency = namedtuple('Agency', ['agency_id', 'agency_name', 'agency_url', 'agency_timezone'])
Stop = namedtuple('Stop', ['stop_id', 'stop_name', 'stop_desc', 'stop_lat', 'stop_lon', 'stop_timezone'])
Route = namedtuple('Route', ['route_id', 'agency_id', 'route_short_name', 'route_long_name', 'route_type'])
Trip = namedtuple('Trip', ['route_id', 'service_id', 'trip_id'])
Fare_rule = namedtuple('Fare_rule', ['fare_id', 'route_id'])
Fare_attribute = namedtuple('Fare_attribute', ['fare_id', 'price', 'currency_type',
                                               'payment_method', 'transfers', 'agency_id'])
Stop_time = namedtuple('Stop_time', ['trip_id', 'arrival_time', 'departure_time', 'stop_id', 'stop_sequence'])
Calendar_date = namedtuple('Calendar_date', ['service_id', 'date', 'exception_type'])

place_codes = defaultdict(dict)
agencies = dict()
stops = dict()
routes = dict()
trips = dict()
fare_rules = dict()
fare_attributes = dict()
stop_times = defaultdict(set)
calendar_dates = defaultdict(set)


def read_stops_from_file(filename):
    raw_stops = []
    with open(filename, 'r') as infile:
        reader = csv.reader(infile, dialect='excel', delimiter=',')
        headers = next(reader, None)
        headers[0] = headers[0].replace(u'\ufeff', '')  # remove byte-order-mark, if present
        stop_tuple = namedtuple("Stop_record", headers)

        for row in reader:
            record = stop_tuple(*row)
            raw_stops.append(record)
    return raw_stops


def process_stops(raw_stops):
    for record in raw_stops:
        place_code = record.place_code
        stop_id = record.stop_id
        agency_id = record.marketing_carrier_code

        update_place_codes(place_code, agency_id, stop_id)
        update_stops(stop_id, record)


def read_schedule_from_file(filename):
    schedule = []
    with open(filename, 'r', encoding='utf-8') as infile:
        reader = csv.reader(infile, dialect='excel', delimiter=';')
        headers = next(reader, None)
        headers[0] = headers[0].replace(u'\ufeff', '')    # remove byte-order-mark, if present

        schedule_tuple = namedtuple("Schedule_record", headers)
        for row in reader:
            record = schedule_tuple(*row)
            schedule.append(record)
    return schedule


def process_schedule(schedule, valid_agencies, max_segments):
    for record in schedule:
        if record.prijevoznik not in valid_agencies:
            continue
        if int(record.broj_segmenata) > max_segments:
            continue

        departure = datetime.strptime(record.polazak, '%b  %d %Y  %I:%M%p')
        arrival = datetime.strptime(record.dolazak, '%b  %d %Y  %I:%M%p')
        departure_date = departure.strftime('%Y%m%d')
        departure_time = departure.strftime('%H:%M')
        arrival_time = arrival.strftime('%H:%M')

        agency_id = valid_agencies.get(record.prijevoznik).get('code')
        route_id = '_'.join((agency_id, record.id_ulaz, record.id_izlaz, record.cijena))
        fare_id = '_'.join((agency_id, record.cijena))
        trip_id = '_'.join((agency_id, record.id_ulaz, departure_time, record.id_izlaz, arrival_time))

        update_agencies(agency_id, record)
        update_routes(route_id, agency_id, record)
        update_fare_rules(fare_id, route_id)
        update_fare_attributes(fare_id, agency_id, record)
        update_trips(trip_id, route_id)
        update_calendar_dates(trip_id, departure_date)
        update_stop_times(trip_id, agency_id, departure, arrival, record)


def get_stop_id_by_place_code(place_code, agency_id):
    try:
        stop_id = place_codes[place_code][agency_id]
    except KeyError:
        stop_id = next(iter(place_codes[place_code].values()))  # any agency with that code
    return stop_id


def update_place_codes(place_code, agency_id, stop_id):
    if place_code not in place_codes or agency_id not in place_codes[place_code]:
        place_codes[place_code][agency_id] = stop_id


def update_stops(stop_id, record):
    if stop_id not in stops:
        stop = Stop(
            stop_id=stop_id,
            stop_name=record.stop_name,
            stop_desc=record.stop_desc.replace('\n', ''),
            stop_lat=float(record.stop_lat),
            stop_lon=float(record.stop_lon),
            stop_timezone=record.stop_timezone,
        )
        stops[stop_id] = stop


def update_agencies(agency_id, record):
    if agency_id not in agencies:
        agency = Agency(
            agency_id=agency_id,
            agency_name=record.prijevoznik,
            agency_url=AGENCIES.get(record.prijevoznik).get('url'),
            agency_timezone=TIMEZONE,
        )
        agencies[agency_id] = agency


def update_routes(route_id, agency_id, record):
    if route_id not in routes:
        departure_stop_id = get_stop_id_by_place_code(record.id_ulaz, agency_id)
        arrival_stop_id = get_stop_id_by_place_code(record.id_izlaz, agency_id)
        departure_stop_name = stops.get(departure_stop_id).stop_name
        arrival_stop_name = stops.get(arrival_stop_id).stop_name
        route = Route(
            route_id=route_id,
            agency_id=agency_id,
            route_short_name='',
            route_long_name=f'{departure_stop_name} - {arrival_stop_name} for {record.cijena} by {record.prijevoznik}',
            route_type=ROUTE_TYPE,
        )
        routes[route_id] = route


def update_fare_rules(fare_id, route_id):
    if fare_id not in fare_rules:
        fare_rule = Fare_rule(
            fare_id=fare_id,
            route_id=route_id,
        )
        fare_rules[fare_id] = fare_rule


def update_fare_attributes(fare_id, agency_id, record):
    if fare_id not in fare_attributes:
        fare_attribute = Fare_attribute(
            fare_id=fare_id,
            price=float(record.cijena),
            currency_type=CURRENCY_TYPE,
            payment_method=PAYMENT_METHOD,  
            transfers='',
            agency_id=agency_id,
        )
        fare_attributes[fare_id] = fare_attribute


def update_trips(trip_id, route_id):
    if trip_id not in trips:
        trip = Trip(
            route_id=route_id,
            service_id=trip_id,
            trip_id=trip_id,
        )
        trips[trip_id] = trip


def update_calendar_dates(service_id, departure_date):
    calendar_date = Calendar_date(
        service_id=service_id,
        date=departure_date,
        exception_type=1,
    )
    calendar_dates[service_id].add(calendar_date)


def add_24_hours(time):
    """ Add 24 hours to time, e.g. 12:34:00 -> 36:34:00 """
    hours, minutes, seconds = time.split(':')
    hours = str(int(hours) + 24)
    return ':'.join((hours, minutes, seconds))


def update_stop_times(trip_id, agency_id, departure, arrival, record):
    if trip_id not in stop_times:
        departure_stop_id = get_stop_id_by_place_code(record.id_ulaz, agency_id)
        arrival_stop_id = get_stop_id_by_place_code(record.id_izlaz, agency_id)

        departure_time = departure.strftime('%H:%M:%S')
        arrival_time = arrival.strftime('%H:%M:%S')
        if arrival.date() > departure.date():
            arrival_time = add_24_hours(arrival_time)

        # two different stop times for starting and ending points of the route
        departure_stop_time = Stop_time(
            trip_id=trip_id,
            arrival_time=departure_time,
            departure_time=departure_time,
            stop_id=departure_stop_id,
            stop_sequence=1,
        )

        arrival_stop_time = Stop_time(
            trip_id=trip_id,
            arrival_time=arrival_time,
            departure_time=arrival_time,
            stop_id=arrival_stop_id,
            stop_sequence=2,
        )

        stop_times[trip_id].add(departure_stop_time)
        stop_times[trip_id].add(arrival_stop_time)


def filter_stops(unfiltered_stops):
    used_stops = set()
    for trip in stop_times.values():
        for stop_time in trip:
            used_stops.add(stop_time.stop_id)
    return {key: value for key, value in unfiltered_stops.items() if key in used_stops}


def save_dict_to_file(data_dict, headers, filename):
    with open(filename, 'w', newline='\n', encoding='utf-8') as outfile:
        writer = csv.writer(outfile, dialect='excel')
        writer.writerow(headers)

        if isinstance(data_dict, defaultdict):
            for data_set in data_dict.values():
                for record in data_set:
                    writer.writerow(list(record))
        else:
            for record in data_dict.values():
                writer.writerow(list(record))


def main():
    parser = argparse.ArgumentParser(
        description='GTFS converter',
        usage="""gtfs.py -stops stops_file -schedule schedule_file -o archive -max_segments N -agencies 'Agency1, ...'
    """)
    parser.add_argument('-stops', dest="stops_file", action="store", metavar='stops_file',
                        type=str, help=".csv file with stops information")
    parser.add_argument('-schedule', dest="schedule_file", action="store", metavar='schedule_file',
                        type=str, help=".csv file with schedule information")
    parser.add_argument('-o', dest="output_file", metavar='output_file', type=str,
                        help='output GTFS archive')
    parser.add_argument('-max_segments', metavar='max_segments', type=int,
                        help='Maximum amount of segments in trip')
    parser.add_argument('-agencies', metavar='valid_agencies', type=str, required=True,
                        help='List of valid agency codes ("ASLU, AUTT, APOE, PANT")')
    options = parser.parse_args()

    agencies_list = [agency.strip().upper() for agency in options.agencies.split(',')]
    valid_agencies = {key: value for key, value in AGENCIES.items() if value.get('code') in agencies_list}

    stops_file = options.stops_file if options.stops_file else DEFAULT_STOPS_FILE
    schedule_file = options.schedule_file if options.schedule_file else DEFAULT_SCHEDULE_FILE
    output_file = options.output_file if options.output_file else DEFAULT_OUTPUT_FILE
    max_segments = options.max_segments if options.max_segments else DEFAULT_MAX_SEGMENTS

    raw_stops = read_stops_from_file(stops_file)
    process_stops(raw_stops)

    schedule = read_schedule_from_file(schedule_file)
    process_schedule(schedule, valid_agencies, max_segments)
    filtered_stops = filter_stops(stops)

    files = [
        (agencies, Agency._fields, 'agency.txt'),
        (filtered_stops, Stop._fields, 'stops.txt'),
        (routes, Route._fields, 'routes.txt'),
        (trips, Trip._fields, 'trips.txt'),
        (fare_rules, Fare_rule._fields, 'fare_rules.txt'),
        (fare_attributes, Fare_attribute._fields, 'fare_attributes.txt'),
        (stop_times, Stop_time._fields, 'stop_times.txt'),
        (calendar_dates, Calendar_date._fields, 'calendar_dates.txt'),
    ]

    with zipfile.ZipFile(output_file, mode='w', compression=zipfile.ZIP_DEFLATED) as archive:
        for file in files:
            save_dict_to_file(*file)
            archive.write(file[-1])
            os.remove(file[-1])


if __name__ == "__main__":
    main()
