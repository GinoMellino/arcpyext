import logging
import re
from itertools import izip_longest

import arcpy

from ..exceptions import MapLayerError, DataSourceUpdateError, UnsupportedLayerError, ChangeDataSourcesError
from ..arcobjects import init_arcobjects_context, destroy_arcobjects_context, list_layers

# Configure module logging
logger = logging.getLogger("arcpyext.mapping")

def change_data_sources(map, data_sources):
    """ """
    errors = []
    data_tables = arcpy.mapping.ListTableViews(map)
    layers_by_df = [arcpy.mapping.ListLayers(df) for df in arcpy.mapping.ListDataFrames(map)]

    if not 'layers' in data_sources or not 'tableViews' in data_sources:
        raise ChangeDataSourcesError("Data sources dictionary does not contain both 'layers' and 'tableViews' keys")

    for layers, layer_sources in izip_longest(layers_by_df, data_sources["layers"]):

        if layer_sources == None or len(layers) != len(layer_sources):
            raise ChangeDataSourcesError("Number of layers does not match number of data sources.")

        for layer, layer_source in izip_longest(layers, layer_sources):
            try:
                if layer_source == None:
                    continue

                if not layer.supports("dataSource") or not layer.supports("workspacePath"):
                    #error on layers that we can't change
                    raise UnsupportedLayerError(layer = layer)


                if layer.supports("dataSource"):
                    logger.debug(u"Layer '{0}': Current datasource: '{1}'".format(layer.longName, layer.dataSource).encode("ascii", "ignore"))

                logger.debug(u"Layer '{0}': Attempting to change workspace path".format(layer.longName).encode("ascii", "ignore"))
                _change_data_source(layer, layer_source["workspacePath"], layer_source.get("datasetName"), layer_source.get("workspaceType"), layer_source.get("schema"))
                logger.debug(u"Layer '{0}': Workspace path updated to: '{1}'".format(layer.name, layer_source["workspacePath"]).encode("ascii", "ignore"))

                if layer.supports("dataSource"):
                    logger.debug(u"Layer '{0}': New datasource: '{1}'".format(layer.longName, layer.dataSource).encode("ascii", "ignore"))

            except MapLayerError as mle:
                errors.append(mle)

    if not len(data_tables) == len(data_sources['tableViews']):
        raise ChangeDataSourcesError("Number of data tables does not match number of data table data sources.")

    for data_table, layer_source in izip_longest(data_tables, data_sources['tableViews']):
        try:
            if layer_source == None:
                continue

            logger.debug(u"Data Table '{0}': Attempting to change workspace path".format(data_table.name).encode("ascii", "ignore"))
            _change_data_source(data_table, layer_source["workspacePath"], layer_source.get("datasetName"), layer_source.get("workspaceType"), layer_source.get("schema"))
            logger.debug(u"Data Table '{0}': Workspace path updated to: '{1}'".format(data_table.name, layer_source["workspacePath"]).encode("ascii", "ignore"))

        except MapLayerError as mle:
            errors.append(mle)

    if not len(errors) == 0:
        raise ChangeDataSourcesError("A number of errors were encountered whilst change layer data sources.", errors)

def create_replacement_data_sources_list(document_data_sources_list, data_source_templates, raise_exception_no_change = False):
    template_sets = [dict(template.items() + [("matchCriteria", set(template["matchCriteria"].items()))]) for template in data_source_templates]

    def match_new_data_source(item):
        if item == None:
            return None

        new_conn = None
        for template in template_sets:
            # The item variable is a layer object which contains a fields property (type list) that can't be serialised and used in set operations
            # It is not required for datasource matching, so exclude it from the the set logic
            hashable_layer_fields = [f for f in item.items() if type(f[1]) is not list]
            if template["matchCriteria"].issubset(set(hashable_layer_fields)):
                new_conn = template["dataSource"]
                break
        if new_conn == None and raise_exception_no_change:
            raise RuntimeError("No matching data source was found for layer")
        return new_conn

    return {
        "layers": [[match_new_data_source(layer) for layer in df] for df in document_data_sources_list["layers"]],
        "tableViews": [match_new_data_source(table) for table in document_data_sources_list["tableViews"]]
    }

def list_document_data_sources(map):
    """List the data sources for each layer or table view of the specified map.

    Outputs a dictionary containing two keys, "layers" and "tableViews".

    "layers" contains an array, with each element representing a data frame (as another array) that contains a
    dictionary of layer details relevant to that layer's connection to its data source.

    "tableViews" is also an array, where each element is a dictionary of table view details relevant to that table
    view's connection to its data source.

    The order of array elements is as displayed in the ArcMap table of contents.

    An example of the output format is the following::

        {
            "layers": [
                [
                    # Data frame number one
                    {
                        # Layer number one
                        "id":               "Layer ID",
                        "name":             "Layer Name",
                        "longName":         "Layer Group/Layer Name",
                        "datasetName":      "(Optional) dataset name",
                        "dataSource":       "(Optional) data source name",
                        "serviceType":      "(Optional) service type, e.g. SDE, MapServer, IMS",
                        "userName":         "(Optional) user name",
                        "server":           "(Optional) server address/hostname",
                        "service":          "(Optional) name or number of the ArcSDE Service",
                        "database":         "(Optional) name of the database",
                        "workspacePath":    "(Optional) workspace path"
                        "visible":          "(Optional) visibility"
                        "definitionQuery":  "definition query on the layer"
                    },
                    # ...more layers
                ],
                # ...more data frames
            ],
            "tableViews": [
                {
                    "datasetName":          "dataset name",
                    "dataSource":           "data source",
                    "definitionQuery":      "definition query on the table",
                    "workspacePath":        "workspace path"
                }
            ]
        }

    :param map: The map to gather data source connection details about
    :type map: arcpy.mapping.MapDocument
    :returns: dict

    """
    layers = [[_get_layer_details(layer) for layer in arcpy.mapping.ListLayers(df)] for df in arcpy.mapping.ListDataFrames(map)]
    tableViews = [_get_table_details(table) for table in arcpy.mapping.ListTableViews(map)]

    # Enrich arcpy data with additional information that is only accessible via arcobjects 
    try:

        init_arcobjects_context()
        additional_layer_info = list_layers(map.filePath)
        destroy_arcobjects_context()

        for layerGroup in layers:
            for l in layerGroup:
                if l is not None:
                    layerName = l['name']
                    # print("layer %s" % layerName)                
                    layer_info = additional_layer_info[layerName]
                    if layer_info is not None:
                        l["id"] = layer_info['id']
                        l["hasFixedId"] = layer_info['hasFixedId']
                        l["visible"] = layer_info['visible']
                        l["definitionQuery"] = layer_info['definitionQuery']
        


    except Exception as e:
        print("Could not read additional layer info using arcobjects")
        print(e)

    return {
        "layers": layers,
        "tableViews": tableViews
    }

def compare(mapA, mapB):
    """Compares two map documents.

    Outputs a list describing any differences

    :param mapA: A map to compare
    :type mapA: arcpy.mapping.MapDocument
    :param mapB: Another version of the same map to compare
    :type mapB: arcpy.mapping.MapDocument
    :returns: dict

    """

    # 
    # Compare data frames
    # 
    def compare_data_frames():
    
        data_frame_count_changed = 301
        data_frame_cs_code_changed = 302
        data_frame_cs_name_changed = 303
        data_frame_cs_type_changed = 304
        diff = []

        try:

            data_frame_a = [x for x in arcpy.mapping.ListDataFrames(mapA) if x.type == "DATAFRAME_ELEMENT"]
            data_frame_b = [x for x in arcpy.mapping.ListDataFrames(mapB) if x.type == "DATAFRAME_ELEMENT"]

            lenA = len(data_frame_a)
            lenB = len(data_frame_b)

            if lenB == 0 or lenA != lenB:
                diff.append({
                    "type": data_frame_count_changed,
                    "was": lenA,
                    "now": lenB
                })

            for index, a in enumerate(data_frame_a):

                b = data_frame_b[index]
                   
                if a.spatialReference.factoryCode != b.spatialReference.factoryCode:
                    diff.append({
                        "type": data_frame_cs_code_changed,
                        "was": a.spatialReference.factoryCode,
                        "now": b.spatialReference.factoryCode,
                    })

                if a.spatialReference.type != b.spatialReference.type:
                    diff.append({
                        "type": data_frame_cs_type_changed,
                        "was": a.spatialReference.type,
                        "now": b.spatialReference.type,
                    })                    

                if a.spatialReference.name != b.spatialReference.name:
                    diff.append({
                        "type": data_frame_cs_name_changed,
                        "was": a.spatialReference.name,
                        "now": b.spatialReference.name,
                    })                                        
                
        except Exception as e:
            print("Error comparing data frames")
            print(e)

        finally:
            return diff           

    # 
    # Compare layers
    # 
    def compare_layers():

        try:    

            # Scalar equality check
            eq = lambda a, b, k: b[k] == a[k] if k in a and k in b else False    

            # Dictionary equality check. Sort is used to ensure consistent order before comparision
            def _sort(obj):
                if isinstance(obj, dict):
                    return sorted((k, _sort(v)) for k, v in obj.items())
                if isinstance(obj, list):
                    return sorted(_sort(x) for x in obj)
                else:
                    return obj

            arrEq = lambda a, b, k: _sort(a[k]) == _sort(b[k]) if k in a and k in b else False
            
            # Who are you? Who am I? 
            def _express_diff(a, b, k, type):
                return {
                    "type": type,
                    "was": a[k] if k in a else None,
                    "now": b[k] if k in b else None
                }    


            def _layer_diff(a, b):

                # Layer change reasons
                layer_id_changed = 401
                layer_name_changed = 402
                layer_datasource_changed = 403
                layer_visibility_changed = 404
                layer_fields_changed = 405
                layer_definition_query_changed = 406

                diff = []

                tests = [
                    {
                        "k": "id",
                        "v": layer_id_changed
                    },
                    {
                        "k": "name",
                        "v": layer_name_changed
                    },
                    {
                        "k": "visible",
                        "v": layer_visibility_changed
                    },
                    {
                        "k": "workspacePath",
                        "v": layer_datasource_changed
                    },
                    {
                        "k": "datasetName",
                        "v": layer_datasource_changed
                    },
                    {
                        "k": "database",
                        "v": layer_datasource_changed
                    },
                    {
                        "k": "server",
                        "v": layer_datasource_changed
                    },
                    {
                        "k": "service",
                        "v": layer_datasource_changed
                    },
                    {
                        "k": "definitionQuery",
                        "v": layer_definition_query_changed
                    },
                    {
                        # Array fields must provide a hash function. This is used to create a UID that can be used for hashset comparison. 
                        # An unhash function must also be provided to reverse lookup the raw dict from a hash ID
                        "k": "fields",
                        "v": layer_fields_changed,
                        "array": True,
                        "hash": lambda _dict: "%s|%s|%s" % (_dict['index'], _dict['name'], _dict['visible']),
                        "unhash": lambda hash: hash.split("|")[0]
                    }
                ]

                # Test each property for changes
                for test in tests:

                    k =  test["k"]
                    v =  test["v"]
                    isArray = test["array"] == True if "array" in test else False

                    if k in a or k in b:

                        if isArray == True:

                            # Set comparsion. Find the difference between A and B
                            hash = test["hash"]
                            unhash = test["unhash"]

                            hashed_a = [hash(_dict) for _dict in a[k]]
                            hashed_b = [hash(_dict) for _dict in b[k]]

                            if set(hashed_a) != set(hashed_b):

                                was = list(set(hashed_a).difference(set(hashed_b)))
                                now = list(set(hashed_b).difference(set(hashed_a)))

                                # print ("was", was)
                                # print ("now", now)

                                def inflate(arr, index):
                                    return [x for x in arr if x['index'] == int(index)][0]                                

                                was = [inflate(a[k], x) for x in [unhash(x) for x in was]]
                                now = [inflate(b[k], x) for x in [unhash(x) for x in now]]

                                # print(was)
                                # print(now)

                                diff.append({
                                    "type": v,
                                    "was": was, 
                                    "now": now
                                })

                        else:
                            if not eq(a, b, k):
                                diff.append(_express_diff(a, b, k, v))
            
                return diff 
        
            a = list_document_data_sources(mapA)
            b = list_document_data_sources(mapB)

            # Flatten layer structure 
            aLayers = [item for sublist in a['layers'] for item in sublist if item is not None]
            bLayers = [item for sublist in b['layers'] for item in sublist if item is not None]
            
            # To correlate a layer in map a and map b, we run a series of specificity tests. Tests are ordered from 
            # most specific, to least specific. These tests apply a process of elimination methodology to correlate layers 
            # between the 2 maps            
            added = []
            updated = []
            removed = []
            resolvedA = {}
            resolvedB = {}
            isResolvedA = lambda x: x['name'] in resolvedA
            isResolvedB = lambda x: x['name'] in resolvedB
            sameId = lambda a, b: eq(a, b, 'id')
            sameName = lambda a, b: eq(a, b, 'name')
            sameDatasource = lambda a, b: eq(a, b, 'datasetName')

            tests = [
                {
                    'fn': lambda a, b: b if sameId(a, b) and sameName(a, b) and sameDatasource(a, b) else None, 
                    'desc': "same id/name and datasource. Unchanged", 
                    'ignore': True
                },
                {
                    'fn': lambda a, b: b if sameId(a, b) and sameName(a, b) and not isResolvedA(a) and not isResolvedB(b) else None,
                    'desc': "same name and id, datasource changed"
                },
                {
                    'fn': lambda a, b: b if sameId(a, b) and sameDatasource(a, b) and not isResolvedA(a) and not isResolvedB(b) else None, 
                    'desc': "same id and datasource, name changed"
                },
                {
                    # TODO this should be skipped if we can verify that fixed layer IDs are not used
                    'fn': lambda a, b: b if sameId(a, b) and not isResolvedA(a) and not isResolvedB(b) else None, 
                    'desc': "same id. Assumed valid if fixed data sources enabled" 
                },            
                {
                    'fn': lambda a, b: b if sameName(a, b) and sameDatasource(a, b) and not isResolvedA(a) and not isResolvedB(b) else None, 
                    'desc': "same name and datasource, id changed"
                },
                {
                    'fn': lambda a, b: b if sameName(a, b) and not isResolvedA(a) and not isResolvedB(b) else None, 
                    'desc': "same name, id/datasource changed"
                },
            ]

            # For every b layer, run a series of tests to find the correlating A layer (if any)
            for bLayer in bLayers:
                match = None

                # Find A layer that correlates to B layer
                for aLayer in aLayers:
                    for index, test in enumerate(tests):
                        matcher = test['fn']
                        desc = test['desc']
                        ignore = True if 'ignore' in test and test['ignore'] == True else False
                        match = matcher(aLayer, bLayer)
                        if match is not None:

                            # Updated layer
                            resolvedA[aLayer['name']] = True
                            resolvedB[bLayer['name']] = True
                            bLayer['diff'] = _layer_diff(aLayer, bLayer)
                            
                            # Add layers that have changes (and are not skipped by the ignore flag) to the result list
                            if not ignore or len(bLayer['diff']) > 0:
                                updated.append(bLayer)                        
                                break
                
                # New layer
                if match is None and not isResolvedB(bLayer):
                    resolvedB[bLayer['name']] = True
                    added.append(bLayer)
        
            # Removed layers
            # print(11111, resolvedA)
            for aLayer in aLayers:
                if not isResolvedA(aLayer):
                    resolvedA[aLayer['name']] = True
                    removed.append(aLayer)

            # print('resolvedA', resolvedA)
            # print('resolvedB', resolvedB)

        except Exception as e:
            print("Error comparing layers")
            print(e)

        finally:
            return {
                'added': added,
                'updated': updated,
                'removed': removed
            }

    return {
        'dataFrames': compare_data_frames(),
        'layers': compare_layers()
    }


def validate_map(map):
    """Analyse the map for broken layers and return a boolean indicating if it is in a valid state or not.

    Lists broken layers on the shell output.

    :param map: The map to be validated
    :type map: arcpy.mapping.MapDocument
    :returns: Boolean, True if valid, False if there are one or more broken layers

    """

    broken_layers = arcpy.mapping.ListBrokenDataSources(map)

    if len(broken_layers) > 0:
        logger.debug(u"Map '{0}': Broken data sources:".format(map.title))
        for layer in broken_layers:
            logger.debug(u" {0}".format(layer.name))
            if not hasattr(layer, "supports"):
                #probably a TableView
                logger.debug(u"  workspace: {0}".format(layer.workspacePath))
                logger.debug(u"  datasource: {0}".format(layer.dataSource))
                continue

            #Some sort of layer
            if layer.supports("workspacePath"):
                logger.debug(u"  workspace: {0}".format(layer.workspacePath))
            if layer.supports("dataSource"):
                logger.debug(u"  datasource: {0}".format(layer.dataSource))

        return False

    return True

def _change_data_source(layer, workspace_path, dataset_name = None, workspace_type = None, schema = None):
    try:
        if ((not hasattr(layer, "supports") or layer.supports("workspacePath")) and
            (dataset_name == None and workspace_type == None and schema == None)):

            # Tests if layer is actually a layer object (i.e. has a "support" function) or table view (which doesn't,
            # but always supports "workspacePath").  Can't test on type (arcpy.mapping.TableView) as that doesn't work
            # on ArcPy 10.0

            layer.findAndReplaceWorkspacePath("", workspace_path, validate = False)
            return

        kwargs = { "validate": False }

        if dataset_name == None and hasattr(layer, "supports") and layer.supports("datasetName"):
            if layer.supports("workspacePath"):
                dataset_name = layer.dataSource.replace(layer.workspacePath, "")
            else:
                dataset_name = layer.datasetName

        if dataset_name != None:
            if (schema != None):
                ds_user, ds_name, fc_user, fc_name = _parse_data_source(dataset_name)

                dataset_name = "{0}.{1}".format(schema, fc_name)

            kwargs["dataset_name"] = dataset_name

        if workspace_type != None:
            kwargs["workspace_type"] = workspace_type

        layer.replaceDataSource(workspace_path, **kwargs)

    except Exception, e:
        raise DataSourceUpdateError("Exception raised internally by ArcPy", layer, e)

    if hasattr(layer, "isBroken") and layer.isBroken:
        raise DataSourceUpdateError("Layer is now broken.", layer)


def _get_layer_details(layer):
    if layer.isGroupLayer and not layer.isNetworkAnalystLayer:
        return None

    details = {
        "name": layer.name,
        "longName": layer.longName
    }

    if layer.supports("datasetName"):
        details["datasetName"] = layer.datasetName

    if layer.supports("dataSource"):
        details["dataSource"] = layer.dataSource

    if layer.supports("serviceProperties"):
        details["serviceType"] = layer.serviceProperties["ServiceType"]
        
        if "UserName" in layer.serviceProperties:
            # File GDB doesn't support username and throws an exception
            details["userName"] = layer.serviceProperties["UserName"]

        if layer.serviceProperties["ServiceType"].upper() == "SDE":
            details["server"] = layer.serviceProperties["Server"]
            details["service"] = layer.serviceProperties["Service"]
            details["database"] = layer.serviceProperties["Database"]

    if layer.supports("workspacePath"):
        details["workspacePath"] = layer.workspacePath

    # Fields
    # @see https://desktop.arcgis.com/en/arcmap/10.4/analyze/arcpy-functions/describe.htm
    desc = arcpy.Describe(layer)
    if desc.dataType == "FeatureLayer":
        field_info = desc.fieldInfo
        details["fields"] = []
        for index in range(0, field_info.count):
            details["fields"].append({
                "index": index,
                "name": field_info.getFieldName(index),
                "visible": field_info.getVisible(index) == "VISIBLE"
            })

    return details

def _get_table_details(table):
    return {
        "datasetName": table.datasetName,
        "dataSource": table.dataSource,
        "definitionQuery": table.definitionQuery,
        "workspacePath": table.workspacePath
    }

def _parse_data_source(data_source):
    """Takes a string describing a data source and returns a four-part tuple describing the dataset username, dataset
    name, feature class username and feature class name"""

    dataset_regex = re.compile(
                        r"^(?:\\)?(?P<ds_user>[\w]*?)(?:\.)?(?P<ds_name>[\w]*?(?=\\))(?:\\)?(?P<fc_user>[\w]*?(?=\.))(?:\.)(?P<fc_name>[\w]*?)$",
                        re.IGNORECASE)

    r = dataset_regex.search(data_source)

    if r == None:
        feature_class_regex = re.compile(
                                r"^(?:\\)?(?P<fc_user>[\w]*?(?=\.))(?:\.)(?P<fc_name>[\w]*?)$",
                                re.IGNORECASE)
        r = feature_class_regex.search(data_source)

    if r == None:
        return (None, None, None, data_source)

    r = r.groupdict()

    return (r.get("ds_user"), r.get("ds_name"), r.get("fc_user"), r.get("fc_name"))
