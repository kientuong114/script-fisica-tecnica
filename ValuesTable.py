import tables
from collections import namedtuple, defaultdict
from tabulate import tabulate

response_1d = namedtuple("response_1d", ["field_req", "value_req", "exact", "row", "low_row", "hi_row", "mix_factor"])

response_1d_qlt = namedtuple("response_1d_qlt", ["field_req", "value_req", "row", "groups", "quality"])

response_2d = namedtuple("response_2d",
                         ["arg1", "arg2", "grade", "row", "row_00", "row_01", "row_10", "row_11"])


class ValuesTable:

    def __init__(self, name: str = "table", fields_ids: list = None, fields_tuples: list = None,
                 json_filename: str = "table_fields.json",
                 rows: list = None):
        if (fields_ids is None) == (fields_tuples is None):  # Only one of two options should be provided
            raise ValueError("Wrong number of optional arguments!")
        self._name = name
        self._entries = []  # List of all rows
        self._fields_info = dict()  # Index of all fields in the table, with all infos
        self._groups = defaultdict(dict)
        self._fields = []  # Contains all the fields
        if fields_tuples is not None:
            for item in fields_tuples:
                self._fields.append(item.id)
                self._fields_info[item.id] = item
        if fields_ids is not None:
            fields_dict = tables.load_fields_from_json(json_filename)
            for field_id in fields_ids:
                self._fields.append(fields_dict[field_id].id)
                self._fields_info[field_id] = fields_dict[field_id]
        if rows is not None:
            self.add_rows(rows)
        for key, field in self._fields_info.items():
            if field.group is not None:
                group_dict = field.group
                # Assign field to id, type
                self._groups[group_dict["group_id"]][group_dict["type"]] = field

    def add_rows(self, rows: list):
        for row in rows:
            self.add_row(row)

    def add_row(self, row_string: str):
        row_arr = row_string.strip("\n").split(",")  # Get array from csv
        if len(row_arr) != len(self._fields):
            print(row_arr)
            print(self._fields)
            raise ValueError("Wrong number of items")
        num_row_arr = list(map(lambda x: float(x), row_arr))  # Convert to float
        row_dict = dict(zip(self._fields, num_row_arr))  # Create Dictionary with id as keys
        self._entries.append(row_dict)  # Add entry

    def print_row(self, row):
        for field_id in self._fields:
            field = self._fields_info[field_id]
            float_format = "%%s: %%0.%df %%s" % self._fields_info[field_id].decimals  # Format decimal places
            print(float_format % (field.name, row[field_id], field.unit))

    def print_flanked_rows(self, low_row, row, hi_row):
        for field_id in self._fields:
            field = self._fields_info[field_id]
            decimals = self._fields_info[field_id].decimals
            float_format = "%%s: (%%0.%df) - %%0.%df - (%%0.%df) %%s" % (decimals, decimals, decimals)
            print(float_format % (field.name, low_row[field_id], row[field_id], hi_row[field_id], field.unit))

    def print_response(self, q_response):
        print("Requested %s=%f from %s" % (q_response.field_req, q_response.value_req, self._name))

        if q_response.exact:
            print("Exact Match Found!")
            # self.print_row(q_response.row)
            print(
                tabulate([f'\x1b[31m{v}\x1b[0m' for v in q_response.row.values()], headers=list(q_response.row.keys()),
                         tablefmt='fancy_grid'))
        else:
            print("Interpolated result with quality=%f" % q_response.mix_factor)
            # self.print_flanked_rows(q_response.low_row, q_response.row, q_response.hi_row)
            print(tabulate([q_response.low_row.values(), [f'\x1b[31m{v}\x1b[0m' for v in q_response.row.values()],
                            q_response.hi_row.values()],
                           headers=list(q_response.low_row.keys()), tablefmt='fancy_grid'))

    def query_table_1d(self, arg1: tuple):
        field_id_1, value_1 = arg1
        sorted_fields = list(sorted(self._entries, key=lambda x: x[field_id_1]))  # Sort fields for value
        hit, rows = tables.ordered_search(sorted_fields, value_1, key=lambda x: x[field_id_1])  # Search for key
        if hit:
            return response_1d(field_id_1, value_1, True, rows, None, None, 1.00)  # Exact Match
        # No exact match, need to interpolate
        low_row, high_row = rows[0], rows[1]  # Unpack lower / Higher bound
        qlt = tables.calculate_quality(low_row, high_row, value_1, key=lambda x: x[field_id_1])
        mid_row = tables.interpolate_rows(low_row, high_row, qlt)
        return response_1d(field_id_1, value_1, False, mid_row, low_row, high_row, qlt)

    def query_table_1d_qlt(self, row, arg1):
        group_id, value_1 = arg1
        resp_group = dict()
        if group_id != "x" and group_id not in self._groups:
            raise ValueError("Not an quality dependant quantity")  # Server Observer LOL
        if group_id == "x":
            x = value_1
        else:
            req_l, req_v = row[self._groups[group_id]["l"].id], row[self._groups[group_id]["v"].id]
            x = tables.calculate_quality(req_l, req_v, value_1)
        if not 0 <= x <= 1:
            raise ValueError("Argument out of range")
        for group_key, group_v in self._groups.items():
            l_value = row[group_v["l"].id]
            v_value = row[group_v["v"].id]
            resp_group[group_key] = (1 - x) * l_value + x * v_value
        return response_1d_qlt(group_id, value_1, row, resp_group, x)

    def find_exact_2d(self, arg1, arg2):
        field_id_1, value_1 = arg1
        field_id_2, value_2 = arg2
        row_result = list(filter(lambda row:
                                 tables.float_equals(row[field_id_1], value_1) and tables.float_equals(
                                     row[field_id_2], value_2),
                                 self._entries))
        if len(row_result) == 0:
            return None
        else:
            return row_result[0]

    def query_table_2d(self, arg1: tuple, arg2: tuple):
        field_id_1, value_1 = arg1
        field_id_2, value_2 = arg2
        if field_id_1 == field_id_2:  # The two fields should be differnt
            raise ValueError("Dependant field error")
        ord_rows = list(sorted(self._entries, key=lambda row: (row[field_id_1], row[field_id_2])))
        values_1 = list(sorted(set(map(lambda x: x[field_id_1], self._entries))))
        values_2 = list(sorted(set(map(lambda x: x[field_id_2], self._entries))))
        hit_1, range_1 = tables.ordered_search(values_1, value_1)  # Search for key
        hit_2, range_2 = tables.ordered_search(values_2, value_2)  # Search for key
        if hit_1 and hit_2:  # Exact Match, no interpolation needed
            row_result = self.find_exact_2d(arg1, arg2)
            return response_2d(arg1, arg2, 0, row_result, None, None, None, None)
        elif hit_2 and not hit_1:  # Linear interpolation
            return self.query_table_2d(arg2, arg1)  # Redo search inverting parameteres
        elif hit_1 and not hit_2:  # Linear interpolation
            filtered_rows_2 = list(filter(lambda row: tables.float_equals(row[field_id_1], value_1), ord_rows))
            qlt = tables.calculate_quality(range_2[0], range_2[1], value_2)
            _, rows = tables.ordered_search(filtered_rows_2, value_2, key=lambda x: x[field_id_2])  # Search for key
            mid_row = tables.interpolate_rows(rows[0], rows[1], qlt)
            return response_2d(arg1, arg2, 1, mid_row, rows[0], rows[1], None, None)
        else:  # Bi-linear interpolation
            neighbors = list()
            for i in range(2):
                neighbors.append([])
                for j in range(2):
                    neighbors[i].append(self.find_exact_2d((field_id_1, range_1[i]), (field_id_2, range_2[j])))
            # Interpolate the left and the right rows in the table
            qlt10 = tables.calculate_quality(neighbors[0][0], neighbors[1][0], value_1, lambda x: x[field_id_1])
            row0 = tables.interpolate_rows(neighbors[0][0], neighbors[1][0], qlt10)
            qlt11 = tables.calculate_quality(neighbors[0][1], neighbors[1][1], value_1, lambda x: x[field_id_1])
            row1 = tables.interpolate_rows(neighbors[0][1], neighbors[1][1], qlt11)
            # Final interpolation
            qlt = tables.calculate_quality(row0, row1, value_2, lambda x: x[field_id_2])
            mid_row = tables.interpolate_rows(row0, row1, qlt)
            return response_2d(arg1, arg2, 2, mid_row, neighbors[0][0], neighbors[0][1],
                               neighbors[1][0], neighbors[1][1])
