distance_mi = 5
is_raining = False
has_bike = True
has_car = False
has_ride_share_app = True
if not distance_mi:
    print("False")
elif distance_mi <= 1 and is_raining!=True:
        print("True")
elif distance_mi <=1 and is_raining:
        print("False")
elif 1<distance_mi<=6 and is_raining and not has_bike:
    print("False")
elif 1<distance_mi<=6 and not is_raining and not has_bike:
    print("False")
elif 1<distance_mi<=6 and not is_raining and has_bike:
    print("True")
elif 1<distance_mi<=6 and is_raining and has_bike:
    print("False")
elif distance_mi >6 and has_ride_share_app:
    print("True")
elif distance_mi>6 and has_car:
    print("True")
elif distance_mi >6 and not (has_ride_share_app and has_car):
    print("False")