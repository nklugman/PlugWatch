#!/usr/bin/env python
from pyspark.sql import SparkSession
from pyspark.sql.functions import col, window, asc, desc, lead, lag, udf, hour, month, dayofmonth, dayofyear, collect_list, lit, year, date_trunc, dayofweek, when, unix_timestamp, array
import pyspark.sql.functions as F
from pyspark.sql.window import Window
from pyspark.sql.types import FloatType, IntegerType, DateType, TimestampType, LongType
from pyspark import SparkConf
from datetime import datetime, timedelta
import os
from math import isnan
import argparse
import json
import calendar

#read arguments
parser = argparse.ArgumentParser()
parser.add_argument('result')
parser.add_argument('user')
parser.add_argument('password')
args = parser.parse_args()

#initiate spark context
spark = SparkSession.builder.appName("SAIDI/SAIFI cluster size").getOrCreate()

### It's really important that you partition on this data load!!! otherwise your executors will timeout and the whole thing will fail
start_time = '2018-07-01'
end_time = '2018-12-01'
cluster_distance_seconds = 180
CD = cluster_distance_seconds

#Roughly one partition per week of data is pretty fast and doesn't take too much chuffling
num_partitions = int((datetime.strptime(end_time,"%Y-%m-%d").timestamp() - datetime.strptime(start_time,"%Y-%m-%d").timestamp())/(7*24*3600))

# This builds a list of predicates to query the data in parrallel. Makes everything much faster
start_time_timestamp = calendar.timegm(datetime.strptime(start_time, "%Y-%m-%d").timetuple())
end_time_timestamp = calendar.timegm(datetime.strptime(end_time, "%Y-%m-%d").timetuple())
stride = (end_time_timestamp - start_time_timestamp)/num_partitions
predicates = []
for i in range(0,num_partitions):
    begin_timestamp = start_time_timestamp + i*stride
    end_timestamp = start_time_timestamp + (i+1)*stride
    pred_string = "time >= '" + datetime.utcfromtimestamp(int(begin_timestamp)).strftime("%Y-%m-%d %H:%M:%S")
    pred_string += "' AND "
    pred_string += "time < '" + datetime.utcfromtimestamp(int(end_timestamp)).strftime("%Y-%m-%d %H:%M:%S") + "'"
    predicates.append(pred_string)

#This query should only get data from deployed devices in the deployment table
query = ("""
    (SELECT powerwatch.core_id, time, is_powered, product_id, millis, last_unplug_millis,
            last_plug_millis, d.location_latitude, d.location_longitude, d.site_id FROM
    powerwatch
    INNER JOIN (
      SELECT core_id,
             site_id,
        location_latitude,
        location_longitude,
        COALESCE(deployment_start_time, '1970-01-01 00:00:00+0') as st,
        COALESCE(deployment_end_time, '9999-01-01 00:00:00+0') as et
      FROM deployment) d ON powerwatch.core_id = d.core_id
    WHERE time >= st AND time <= et AND """ +
        "time >= '" + start_time + "' AND " +
        "time < '" + end_time + "' AND " +
        "(product_id = 7008 OR product_id = 7009 or product_id = 7010 or product_id = 7011 or product_id = 8462)) alias")

pw_df = spark.read.jdbc(
            url = "jdbc:postgresql://timescale.ghana.powerwatch.io/powerwatch",
            table = query,
            predicates = predicates,
            properties={"user": args.user, "password": args.password, "driver":"org.postgresql.Driver"})

query = "(select site_id, tx, feeder_id from achimota_grid_grouped) alias"
grid = spark.read.jdbc(
            url = "jdbc:postgresql://timescale.ghana.powerwatch.io/powerwatch",
            table = query,
            properties={"user": args.user, "password": args.password, "driver":"org.postgresql.Driver"})




#if you have multiple saves below this prevents reloading the data every time
pw_df.cache()

#join on the grid to get the feeder and tx for each outage
pw_df = pw_df.join(grid, on='site_id', how='inner')

#We should mark every row with the number of unique sensors reporting in +-5 days so we now the denominator for SAIDI/SAIFI
pw_distinct_core_id = pw_df.select("time","core_id","feeder_id","tx")
pw_distinct_core_id_by_feeder = pw_distinct_core_id.groupBy(F.window("time", '10 days', '1 day'),"feeder_id").agg(F.countDistinct("core_id"))
pw_distinct_core_id_by_feeder = pw_distinct_core_id_by_feeder.withColumn("window_mid_point", F.from_unixtime((F.unix_timestamp(col("window.start")) + F.unix_timestamp(col("window.end")))/2))
pw_distinct_core_id_by_feeder = pw_distinct_core_id_by_feeder.select("feeder_id",col("count(DISTINCT core_id)").alias("sensors_reporting"), "window_mid_point")

pw_distinct_core_id_by_tx = pw_distinct_core_id.groupBy(F.window("time", '10 days', '1 day'),"tx").agg(F.countDistinct("core_id"))
pw_distinct_core_id_by_tx = pw_distinct_core_id_by_tx.withColumn("window_mid_point", F.from_unixtime((F.unix_timestamp(col("window.start")) + F.unix_timestamp(col("window.end")))/2))
pw_distinct_core_id_by_tx = pw_distinct_core_id_by_tx.select("tx",col("count(DISTINCT core_id)").alias("sensors_reporting"), "window_mid_point")

#now we need to created a window function that looks at the leading lagging edge of is powered and detects transitions
#then we can filter out all data that is not a transition
w = Window.partitionBy("core_id").orderBy(asc("time"))
pw_df = pw_df.withColumn("previous_power_state", lag("is_powered").over(w))

#filter out every time that the state does not change
pw_df = pw_df.filter(col("previous_power_state") != col("is_powered"))

#now we should only count this if it is an outage (on, off, on)
is_powered_lead = lead("is_powered",1).over(w)
is_powered_lag = lag("is_powered",1).over(w)
pw_df = pw_df.withColumn("lagging_power",is_powered_lag)
pw_df = pw_df.withColumn("leading_power",is_powered_lead)
pw_df = pw_df.withColumn("outage", when((col("is_powered") == 0) & (col("lagging_power") == 1) & (col("leading_power") == 1), 1).otherwise(0))

#now need the most accurate outage time possible for outage event
#now find all the exact outage and restore times using millis
def timeCorrect(time, millis, unplugMillis):
    if(unplugMillis == 0 or millis == None or unplugMillis == None or isnan(millis) or isnan(unplugMillis)):
        return time
    elif unplugMillis > millis:
        return time
    else:
        return time - timedelta(microseconds = (int(millis)-int(unplugMillis))*1000)
udftimeCorrect = udf(timeCorrect, TimestampType())
pw_df = pw_df.withColumn("outage_time", udftimeCorrect("time","millis","last_unplug_millis"))
pw_df = pw_df.withColumn("outage_time", F.unix_timestamp("outage_time"))
pw_df = pw_df.withColumn("r_time", udftimeCorrect("time","millis","last_plug_millis"))
pw_df = pw_df.withColumn("r_time", F.unix_timestamp("r_time"))

#now denote the end time of the outage for saidi reasons
time_lead = lead("r_time",1).over(w)
pw_df = pw_df.withColumn("restore_time", time_lead)

#now filter out everything that is not an outage. We should have a time and end_time for every outage
pw_df = pw_df.filter("outage != 0")


# Okay now that we have the outages and times we should join it with the number of sensors reporting above
# This allows us to calculate the relative portion of each device to SAIDI/SAIFI
#pw_df = pw_df.join(pw_distinct_core_id, F.date_trunc("day", pw_df['outage_time']) == F.date_trunc("day", pw_distinct_core_id["window_mid_point"]))

#record the duration of the outage
#def calculateDuration(startTime, endTime):
#    delta = endTime-startTime
#    seconds = delta.total_seconds()
#    return int(seconds)

#udfcalculateDuration = udf(calculateDuration, IntegerType())
#pw_df = pw_df.withColumn("outage_duration", udfcalculateDuration("outage_time","restore_time"))

#Okay so the best way to actually do outage clustering is through an iterative hierarchical approach

#Steps:
#Iterate:
# Sort by outage time
#   Note the distance to the nearest point in time leading or lagging you
#   Note the distance to of that nearest point to its neighbor
#   If you are closer to your neighbor than it is to it's closest merge and create a new point with a new outage time

def timestamp_average(timestamps):
    seconds = 0
    for i in range(0,len(timestamps)):
        seconds += timestamps[i]

    return int(seconds/len(timestamps))

max_cluster_size = 500
pw_df = pw_df.select(array("core_id").alias("core_id"),
                    array("tx").alias("tx"),
                    array("feeder_id").alias("feeder_id"),
                    "outage_time",
                    array("restore_time").alias("restore_time"),
                    array(F.struct("location_latitude", "location_longitude")).alias("location"))

pw_df = pw_df.withColumn("outage_times", F.array("outage_time"))

#print("Starting with count:", pw_df.count())
pw_finalized_outages = spark.createDataFrame([], pw_df.schema)

# all of the local checkpoints should probably be switched to just checkpoints
# note the checkpointing is CRITICAL to the function of the algorithm in spark
# otherwise the RDD lineage is recalculated every loop and the plan creation time balloons exponentially
# checkpointing truncates the plan
# it is also critical that you reset the reference of the checkpoint
# spark objects are immutable - there is no such thing as an in place modification
# and checkpointing does modify the lineage of the underlying object
# We *might* be able to get away with caching instead but I was having out of memory problems
pw_finalized_outages = pw_finalized_outages.localCheckpoint(eager = True)
pw_df = pw_df.localCheckpoint(eager = True)

#now run the iterative algorithm to cluster the remainder
while pw_df.count() > 0:
    #first prune any outages that are not getting any larger and union them to finalized outages set
    w = Window.partitionBy(F.weekofyear(F.from_unixtime("outage_time"))).orderBy(asc("outage_time"))
    lead1 = lead("outage_time",1).over(w)
    lag1 = lag("outage_time",1).over(w)
    pw_df = pw_df.withColumn("lead1",lead1)
    pw_df = pw_df.withColumn("lag1",lag1)
    merge_time = when(((col("lead1") - col("outage_time") >= CD) | col("lead1").isNull()) & ((col("outage_time") - col("lag1") >= CD) | col("lag1").isNull()), None).otherwise(lit(0))
    pw_df = pw_df.withColumn("merge_time", merge_time)

    pw_final_outages = pw_df.filter(col("merge_time").isNull())
    pw_final_outages = pw_final_outages.select("core_id","tx","feeder_id","outage_time",
                                                "restore_time",
                                                "location", "outage_times")

    pw_finalized_outages = pw_finalized_outages.union(pw_final_outages)
    pw_finalized_outages = pw_finalized_outages.localCheckpoint()
    pw_df = pw_df.filter(col("merge_time").isNotNull())
    pw_df = pw_df.localCheckpoint(eager = True)
    print("Pruned to:", pw_df.count())

    #now do one step of merging for the ones that are still changing
    w = Window.partitionBy(F.weekofyear(F.from_unixtime("outage_time"))).orderBy(asc("outage_time"))
    lead1 = lead("outage_time",1).over(w)
    lead2 = lead("outage_time",2).over(w)
    lag1 = lag("outage_time",1).over(w)
    lag2 = lag("outage_time",2).over(w)
    pw_df = pw_df.withColumn("lead1",lead1)
    pw_df = pw_df.withColumn("lead2",lead2)
    pw_df = pw_df.withColumn("lag1",lag1)
    pw_df = pw_df.withColumn("lag2",lag2)
    pw_df = pw_df.withColumn("diff_lead1", col("lead1") - col("outage_time"))
    pw_df = pw_df.withColumn("diff_lead2", col("lead2") - col("lead1"))
    pw_df = pw_df.withColumn("diff_lag1", col("outage_time") - col("lag1"))
    pw_df = pw_df.withColumn("diff_lag2", col("lag1") - col("lag2"))

    merge_time = when((col("diff_lead1") < CD) &
                      ((col("diff_lead1") <= col("diff_lead2")) | col("diff_lead2").isNull()) &
                      ((col("diff_lead1") <= col("diff_lag1")) | col("diff_lag1").isNull()), col("lead1")).when(
                              (col("diff_lag1") < CD) &
                              ((col("diff_lag1") <= col("diff_lag2")) | col("diff_lag2").isNull()) &
                              ((col("diff_lag1") <= col("diff_lead1")) | col("diff_lead1").isNull()), col("outage_time")).otherwise(None)

    pw_df = pw_df.withColumn("merge_time", merge_time)
    pw_null_merge_time = pw_df.filter(col("merge_time").isNull())
    pw_df = pw_df.filter(col("merge_time").isNotNull())

    pw_df = pw_df.groupBy("merge_time").agg(F.flatten(F.collect_list("core_id")).alias("core_id"),
                                            F.flatten(F.collect_list("tx")).alias("tx"),
                                            F.flatten(F.collect_list("feeder_id")).alias("feeder_id"),
                                            F.flatten(F.collect_list("outage_times")).alias("outage_times"),
                                            F.flatten(F.collect_list("restore_time")).alias("restore_time"),
                                            F.flatten(F.collect_list("location")).alias("location"))

    pw_df = pw_df.select("core_id","outage_times","restore_time","location","tx","feeder_id")
    pw_null_merge_time = pw_null_merge_time.select("core_id","outage_times","restore_time","location","tx","feeder_id")
    pw_df = pw_df.union(pw_null_merge_time)

    udfTimestampAverage = udf(timestamp_average, LongType())
    pw_df = pw_df.withColumn("outage_time", udfTimestampAverage("outage_times"))
    pw_df = pw_df.localCheckpoint(eager = True)
    print("Merged to:", pw_df.count())
    print()

#Okay now we have a list of outages, restore_times, locations, core_ids
#First let's calculate some high level metrics

#size of outages
pw_finalized_outages = pw_finalized_outages.withColumn("cluster_size", F.size(F.array_distinct("core_id")))

# now filter the outages so that at least two devices went out
pw_finalized_outages = pw_finalized_outages.filter(col("cluster_size") >= 2)

# now explode the outage lists so that every line is a sensor involved in that outage and regroup by transformer and feeder
# then each outage maps to a number of sensors out under each transformer and feeder
# This gives the relative SAIFI contribution of each transformer in each outage
pw_outages_by_feeder = pw_finalized_outages.select("outage_time","feeder_id")
pw_outages_by_feeder = pw_outages_by_feeder.withColumn("feeder_id",F.explode("feeder_id"))
pw_outages_by_feeder = pw_outages_by_feeder.withColumn("size",F.lit(1))
pw_outages_by_feeder = pw_outages_by_feeder.groupBy("outage_time","feeder_id").agg(F.sum("size").alias("cluster_size"))
pw_outages_by_feeder = pw_outages_by_feeder.select("outage_time", "cluster_size", col("feeder_id").alias("feeder_id_o"))
pw_outages_by_feeder.show()
pw_outages_by_feeder = pw_outages_by_feeder.join(pw_distinct_core_id_by_feeder, ((F.date_trunc("day", F.from_unixtime(pw_outages_by_feeder["outage_time"])) == F.date_trunc("day", pw_distinct_core_id_by_feeder["window_mid_point"])) & (pw_outages_by_feeder["feeder_id_o"] == pw_distinct_core_id_by_feeder["feeder_id"])))

pw_outages_by_feeder = pw_outages_by_feeder.withColumn("relative_cluster_size",col("cluster_size")/col("sensors_reporting"))
pw_outages_by_feeder = pw_outages_by_feeder.select("outage_time","relative_cluster_size","feeder_id")

pw_outages_by_tx = pw_finalized_outages.select("outage_time","tx")
pw_outages_by_tx = pw_outages_by_tx.withColumn("tx",F.explode("tx"))
pw_outages_by_tx = pw_outages_by_tx.withColumn("size",F.lit(1))
pw_outages_by_tx = pw_outages_by_tx.groupBy("outage_time","tx").agg(F.sum("size").alias("cluster_size"))
pw_outages_by_tx = pw_outages_by_tx.select("outage_time","cluster_size",col("tx").alias("tx_o"))
pw_outages_by_tx = pw_outages_by_tx.join(pw_distinct_core_id_by_tx, ((F.date_trunc("day", F.from_unixtime(pw_outages_by_tx["outage_time"])) == F.date_trunc("day", pw_distinct_core_id_by_tx["window_mid_point"])) & (pw_outages_by_tx["tx_o"] == pw_distinct_core_id_by_tx["tx"])))
pw_outages_by_tx = pw_outages_by_tx.withColumn("relative_cluster_size",col("cluster_size")/col("sensors_reporting"))
pw_outages_by_tx = pw_outages_by_tx.select("outage_time","relative_cluster_size","tx")

### SAIFI ###
#month - monthly SAIFI
outages_feeder_month = pw_outages_by_feeder.select(F.from_unixtime("outage_time").alias("outage_time"),"feeder_id","relative_cluster_size")
outages_feeder_month = outages_feeder_month.withColumn("outage_date_month", date_trunc("month", "outage_time"))
outages_feeder_month = outages_feeder_month.groupBy("feeder_id","outage_date_month").sum()
outages_feeder_month = outages_feeder_month.withColumn("outage_month", month("outage_date_month"))
outages_feeder_month = outages_feeder_month.groupBy("feeder_id","outage_month").avg().alias("monthly_SAIFI").orderBy("outage_month")
outages_feeder_month = outages_feeder_month.select("feeder_id","outage_month",col("avg(sum(relative_cluster_size))").alias("monthly_SAIFI"))
outages_feeder_month.show()
outages_feeder_month.repartition(1).write.format("com.databricks.spark.csv").mode('overwrite').option("header", "true").save(args.result + '/monthly_SAIFI_cluster_size_feeder_gte2')

### SAIFI ###
#month - monthly SAIFI
outages_tx_month = pw_outages_by_tx.select(F.from_unixtime("outage_time").alias("outage_time"),"tx","relative_cluster_size")
outages_tx_month = outages_tx_month.withColumn("outage_date_month", date_trunc("month", "outage_time"))
outages_tx_month = outages_tx_month.groupBy("tx","outage_date_month").sum()
outages_tx_month = outages_tx_month.withColumn("outage_month", month("outage_date_month"))
outages_tx_month = outages_tx_month.groupBy("tx","outage_month").avg().alias("monthly_SAIFI").orderBy("outage_month")
outages_tx_month = outages_tx_month.select("tx","outage_month",col("avg(sum(relative_cluster_size))").alias("monthly_SAIFI"))
outages_tx_month.show()
outages_tx_month.repartition(1).write.format("com.databricks.spark.csv").mode('overwrite').option("header", "true").save(args.result + '/monthly_SAIFI_cluster_size_tx_gte2')
