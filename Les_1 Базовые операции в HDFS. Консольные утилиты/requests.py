#!/usr/bin/env python3.4
import sys
import json
import requests
import re
import psycopg2
import psycopg2.extras
from datetime import datetime
from datetime import timedelta

if len(sys.argv)!=5:
        print('This script is used to get the hdfs directory size other the entire HDFS nad saves it to the postgresql database.')
        print('the script uses the HTTPFS to get the data.')
        print('USAGE')
        print(' save_hdfs_snapshot.py <webhdfs_root> <start_folder> <maximum_depth> <cluster_name> ')
        print('where')
        print(' webhdfs_root:   URL of the WebHDFS server.')
        print(' start_folder:   We\'re starting monitoring from this folder. !!!!!NOTE! It should always end with / !!!!!')
        print(' maximum_depth:  Maximum monitoring depth. We will look no deeper that that into the directory structure.')
        print(' cluster_name:   The name of the cluster we\'re looking at.')
        print('For example')
        print(' save_hdfs_snapshot.py http://foobar.company.ru:14000/webhdfs/v1 /user/ 4 DWH ')
        exit(0)




#Debug switch
DEBUG=False

# WebHDFS root
webhdfs_root=sys.argv[1]
# Starting direcory
startdir=sys.argv[2]
startdepth=startdir.count('/')-1
# We don't want to look deeper that that down the rabbit's hole
maxdepth =int(sys.argv[3])
# Cluster name and current date we're looking at
cluster_name=sys.argv[4]

# Current snapshot date 
now = datetime.now().replace( second=0, microsecond=0)
# current partition name and boundaries
part_name = now.strftime('%Y_%m_%d')
part_startdate= now.replace( minute=0, hour=0, second=0, microsecond=0)
part_enddate = part_startdate+timedelta(1)

# We don't want to look into the directories named like these in the list
stopword_list = ['.Trash','.staging','.cloudera_health_monitoring_canary_files','.sparkStaging','.temp']
# Same as above, but regexp and it is applied to entire path
# This is mainly targeted to exclude partitions from the list.
stopword_list_regex = ['/\w{1,}=\w{1,}/\Z','/hbase/archive/data/default/.{1,}/\Z','/hbase/data/default/.{1,}/\Z','/hbase/WALs/\Z']
# compile regexp right away
slr_compiled = []
for i in stopword_list_regex:
        slr_compiled.append(re.compile(i))


#Postgresql parameters 
pg_dbname='hdfs_monitoring'
pg_user='hdfs_monitor'
pg_password='hello'
pg_host='postgre01.company.ru'

# Misc suff
directories=[]
regexp_stopword_cnt=0
stopword_cnt=0
maxdepth_reached_cnt=0

# ---------------------------------------------------------------------------------------------------------
# This one requests directory size 
def get_space_consumed( path, depth ):
        #if DEBUG: print ('Checking the size of '+path+ ' at depth '+str(depth) )
        
        try:
               # Get the dir size 
               response = requests.get(webhdfs_root+path+'?user.name=hdfs&op=GETCONTENTSUMMARY')
               dir_data=json.loads(response.text)

               dir_info=(path, depth , int(dir_data[ 'ContentSummary' ] [ 'length' ]), int(dir_data[ 'ContentSummary' ] [ 'spaceConsumed' ]))
               directories.append((cluster_name,str(now), path, depth , int(dir_data[ 'ContentSummary' ] [ 'length' ]), int(dir_data[ 'ContentSummary' ] [ 'spaceConsumed' ]),  int(dir_data[ 'ContentSummary' ] [ 'directoryCount' ]), int(dir_data[ 'ContentSummary' ] [ 'fileCount' ])))
        except KeyError:
               if DEBUG: print ('ERROR KeyError:Looks like the '+path+' does not exist. Sorry :( ')
               dir_info=(path, depth , 0, 0)
        except ValueError:
               if DEBUG: print ('ERROR ValueError:Looks like the '+path+' does not exist. Sorry :( ')
               dir_info=(path, depth , 0, 0)

        return dir_info
# ---------------------------------------------------------------------------------------------------------


# ---------------------------------------------------------------------------------------------------------
# Looking into the HDFS directory
def look_into_directory ( path, depth , p_maxdepth):
        
        global stopword_cnt
        global maxdepth_reached_cnt
        global regexp_stopword_cnt

        response = requests.get(webhdfs_root+path+'?user.name=hdfs&op=LISTSTATUS')
        dir_data=json.loads(response.text)

        # increase current depth 
        depth=depth+1
        try:

               for fs_object in dir_data[ 'FileStatuses' ] [ 'FileStatus' ]:
                       if str(fs_object ['type'])=='DIRECTORY':
                               # short directory name goes here 
                               dirname=str(fs_object ['pathSuffix'])
        
                               # get dirsize 
                                # checking the regexps first
                               regexp_found=False
                               for regexp in slr_compiled:
                                      if regexp.search(path + dirname +'/'):
                                              regexp_found=True
                                              regexp_stopword_cnt=regexp_stopword_cnt+1
                                              if DEBUG: print('Stopping on regexp '+str(regexp)+' on directory '+path + dirname +'/')
                                              break;

                               # looking only if the regexp does not match
                               if not regexp_found: dir_info=get_space_consumed(path+dirname ,depth)
                               
                       
                               # Checking the stopword if you know waht I mean hehe :)))
                               if stopword_list.count(dirname) != 0:
                                      # Stopword found 
                                      stopword_cnt=stopword_cnt+1
                               elif depth >= p_maxdepth :
                                      # Stopping at maximum depth 
                                      maxdepth_reached_cnt=maxdepth_reached_cnt+1
                               else:
                                      # Falling onto the directory 
                                      if DEBUG: print (str(path + dirname +'/').rjust(len(path + dirname +'/')+depth,'-'))
                                      look_into_directory ( path + dirname +'/' , depth, p_maxdepth)

        except KeyError:
               print ('ERROR KeyError: Looks like the '+path+' does not exist. Sorry :( ')      
        except ValueError:
               print ('ERROR ValueError:Looks like the '+path+' does not exist. Sorry :( ')
        return
# ---------------------------------------------------------------------------------------------------------



# Lets start to RRUUUUMBLEEEEE!!
print(str(datetime.now())+' Starting data collection.')
look_into_directory( startdir , startdepth, maxdepth)

# Printing out the results just in case
print(str(datetime.now())+' Data collection completed.' )
print(str(datetime.now())+' Stopwords encountered ' +str(stopword_cnt))
print(str(datetime.now())+' Regexp stopwords encountered '+str(regexp_stopword_cnt))
print(str(datetime.now())+' Directories found total '+str(len(directories)))


# adding new partition 
print(str(datetime.now())+' Starting postgresql upload.')
conn = psycopg2.connect(dbname=pg_dbname, user=pg_user, password=pg_password, host=pg_host)
cursor = conn.cursor()

stmt= 'CREATE TABLE IF NOT EXISTS hdfs_dir_stats_'+part_name+' PARTITION OF hdfs_dir_stats FOR VALUES FROM (\''+part_startdate.strftime('%Y-%m-%d')+'\') TO (\''+part_enddate.strftime('%Y-%m-%d')+'\');'
#print(part_name)
#print(part_startdate)
#print(part_enddate)
#print(stmt)
cursor.execute(stmt)
cursor.execute('create index if not exists hdfs_dir_stats_'+part_name+'_idx01 on hdfs_dir_stats_'+part_name+' (datetime,cluster,depth);')
cursor.execute('create index if not exists hdfs_dir_stats_'+part_name+'_idx02 on hdfs_dir_stats_'+part_name+'(datetime,cluster,depth,dirname, raw_size);')
cursor.execute('analyze hdfs_dir_stats_'+part_name+';')

# Now, let's insert into the Postgresql

stmt='insert into hdfs_dir_stats (cluster, datetime, dirname, depth, raw_size, replicated_size, directory_count, file_count) values %s'
psycopg2.extras.execute_values (
    cursor, stmt, directories, template=None, page_size=300
)

conn.commit()

print(str(datetime.now())+' Data uploaded. ')
print(str(datetime.now())+' Data enrichment started. ')

# cursor.execute("""
# update hdfs_dir_stats o
#   set hourly_raw_growth=
#                      raw_size-(SELECT raw_size
#                                         FROM hdfs_dir_stats i 
#                                     WHERE i.cluster=o.cluster 
#                                          AND i.depth=o.depth 
#                                             AND i.dirname=o.dirname 
#                                             AND i.datetime=(SELECT max(datetime) 
#                                                                              FROM hdfs_dir_stats k 
#                                                                          WHERE k.datetime<o.datetime-INTERVAL '1 hour'
#                                                                                   AND k.cluster=%s )
#                                     ) ,
#              daily_raw_growth=
#                      raw_size-(SELECT raw_size
#                                         FROM hdfs_dir_stats i 
#                                     WHERE i.cluster=o.cluster 
#                                          AND i.depth=o.depth 
#                                             AND i.dirname=o.dirname 
#                                             AND i.datetime=(SELECT max(datetime) 
#                                                                              FROM hdfs_dir_stats k 
#                                                                          WHERE k.datetime<o.datetime-INTERVAL '1 day'
#                                                                                   AND k.cluster=%s )
#                      )              
# where datetime=%s
#   and cluster=%s
#   --and dirname='/user/vosipov/hue/successful-call-setup
#""", 
#       (cluster_name,cluster_name,now,cluster_name) )

conn.commit()
cursor.close()
print(str(datetime.now())+' Data enriched. Finished.')
conn.close()

# Done. Enjoy.

