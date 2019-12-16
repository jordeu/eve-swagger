# -*- coding: utf-8 -*-
"""
    eve-swagger.objects
    ~~~~~~~~~~~~~~~~~~~
    swagger.io extension for Eve-powered REST APIs.

    :copyright: (c) 2015 by Nicola Iarocci.
    :license: BSD, see LICENSE for more details.
"""
import sys
from collections import OrderedDict
from requests.utils import quote
from flask import request, current_app as app
from eve.auth import BasicAuth, TokenAuth

from .validation import validate_info
from .paths import get_ref_schema
from .definitions import INFO, HOST


def _key(val):
    return val.replace('/', ' ').replace('_', ' ').replace('-', ' ').title().replace(' ', '')


def _quote(val):
    return quote(val, safe='#/_')


def ref(url):
    return {"$ref": _quote(url)}


def _get_scheme():
    return "http" if app.auth is None else "https"


def info():
    validate_info()

    cfg = app.config[INFO]

    def node(parent, cfg, key):
        value = cfg.get(key)
        if value:
            parent[key] = cfg[key]

    info = OrderedDict()
    node(info, cfg, "title")
    node(info, cfg, "description")
    node(info, cfg, "termsOfService")
    node(info, cfg, "contact")
    node(info, cfg, "license")
    node(info, cfg, "version")

    return info


def servers():
    url = app.config.get(HOST) or "%s://%s" % (_get_scheme(), request.host)
    if app.config["API_VERSION"]:
        url = url + "/" + app.config["API_VERSION"]
    return [{"url": url}]


def responses():
    return {
        "Error": {
            "description": "An error message",
            "content": {
                "application/json": {"schema": ref("#/components/schemas/Error")}
            },
        }
    }


def parameters():
    parameters = OrderedDict()
    # resource parameters
    for (resource_name, rd) in app.config["DOMAIN"].items():
        if resource_name.endswith("_versions") or rd.get("disable_documentation"):
            continue

        title = rd["item_title"]
        if "additional_lookup" in rd:
            lookup_field = rd["additional_lookup"]["field"]
            descr = rd["schema"][lookup_field].get("description") or ""
            example = rd["schema"][lookup_field].get("example") or ""

            p = OrderedDict()
            p["in"] = "path"
            p["name"] = rd["additional_lookup"]["field"].title()
            p["required"] = True
            p["description"] = descr
            p["example"] = example
            p["schema"] = {"type": "string"}

            parameters[_key(title + "_" + lookup_field)] = p

        lookup_field = rd["item_lookup_field"]
        if lookup_field == "_id":
            continue

        eve_type = rd["schema"][lookup_field]["type"]
        descr = rd["schema"][lookup_field].get("description") or ""
        example = rd["schema"][lookup_field].get("example") or ""
        if "data_relation" in rd["schema"][lookup_field]:
            # the lookup field is a copy of another field
            dr = rd["schema"][lookup_field]["data_relation"]

            # resource definition of the data relation source
            source_rd = app.config["DOMAIN"][dr["resource"]]

            # schema of the data relation source field
            source_def = source_rd["schema"][dr["field"]]

            # key in #/definitions/...
            source_def_name = source_rd["item_title"] + "_" + dr["field"]

            # copy description if necessary
            descr = descr or source_def.get("description")
            descr = descr + " (links to {})".format(source_def_name)

        p = OrderedDict()
        p["in"] = "path"
        p["name"] = title.lower() + "Id"
        p["required"] = True
        p["description"] = descr
        if "SWAGGER_EXAMPLE_FIELD_REMOVE" not in app.config:
            p["example"] = example
        ptype = ""
        if eve_type == "objectid" or eve_type == "datetime":
            ptype = "string"
        elif eve_type == "float":
            ptype = "number"
        else:
            # TODO define default
            pass

        p["schema"] = {"type": ptype}
        parameters[_key(title + "_" + lookup_field)] = p

    # add header parameters
    parameters.update(_header_parameters())
    # add query parameters
    parameters.update(_query_parameters())

    # add ObjectId parameter
    r = OrderedDict()
    r["in"] = "path"
    r["name"] = "ResourceId"
    r["required"] = True
    r["description"] = "Resource identifier (the object *'_id'* field)"
    r["schema"] = {"type": "string", "example": "5dcb8754da2720ac4aa11411"}
    parameters["ResourceId"] = r

    return parameters


def _query_parameters():
    params = {}

    r = OrderedDict()
    r["in"] = "query"
    r["name"] = app.config["QUERY_WHERE"]
    r["description"] = 'MongoDB like query expressions to filter the results.'
    r["schema"] = {"type": "string", "example": "{\"number\": 10}"}
    params[_key("query__where")] = r

    r = OrderedDict()
    r["in"] = "query"
    r["name"] = app.config["QUERY_SORT"]
    r["description"] = 'MongoDB like sorting expressions.'
    r["schema"] = {"type": "string", "example": "[(\"lastname\", -1)]"}
    params[_key("query__sort")] = r

    r = OrderedDict()
    r["in"] = "query"
    r["name"] = app.config["QUERY_PAGE"]
    r["description"] = "page to return (starts at one)"
    r["schema"] = {"type": "integer", "example": 1}
    params[_key("query__page")] = r

    r = OrderedDict()
    r["in"] = "query"
    r["name"] = app.config["QUERY_MAX_RESULTS"]
    r["description"] = "maximum items to return per page"
    r["schema"] = {"type": "integer", "example": 25}
    params[_key("query__max_results")] = r

    return params


def _header_parameters():
    r = OrderedDict()
    r["in"] = "header"
    r["name"] = "If-Match"
    r["description"] = "Current value of the _etag field"
    r["required"] = app.config["IF_MATCH"] and app.config["ENFORCE_IF_MATCH"]
    r["schema"] = {"type": "string"}
    return {_key("If-Match"): r}


def request_bodies():
    rbodies = OrderedDict()

    for (resource_name, rd) in app.config["DOMAIN"].items():
        if resource_name.endswith("_versions") or rd.get("disable_documentation"):
            continue

        title = rd["item_title"]
        rb = OrderedDict()
        description = "A {} document.".format(title)
        if rd["bulk_enabled"]:
            description = "A {0} or list of {0} documents".format(title)

        rb["description"] = description
        rb["required"] = True
        rb["content"] = {
            # TODO what about other methods
            "application/json": {
                "schema": get_ref_schema(rd)
            }
        }

        # Add examples
        if "example" in rd:
            if isinstance(rd["example"], list):
                rb["content"]["application/json"]["examples"] = {"{}".format(i): v for i, v in enumerate(rd["example"])}
            else:
                rb["content"]["application/json"]["example"] = rd["example"]

        rbodies[_key(rd["url"])] = rb

    return rbodies


def headers():
    pass


def security_schemes():
    if "flask_oauthlib.provider" in sys.modules.keys():
        url = app.config.get(HOST) or request.host
        return {
            "oAuth2": {
                "type": "oauth2",
                "description": "oAuth2 password credentials.",
                "flows": {
                    "password": {
                        # TODO why does this not work with a relative path?
                        "tokenUrl": url
                        + app.config["SENTINEL_ROUTE_PREFIX"]
                        + app.config["SENTINEL_TOKEN_URL"],
                        "scopes": {},
                    }
                },
            }
        }
    elif isinstance(app.auth, TokenAuth):
        return {"BearerAuth": {"type": "http", "scheme": "bearer"}}
    elif isinstance(app.auth, BasicAuth):
        return {"BasicAuth": {"type": "http", "scheme": "basic"}}
    else:
        pass  # FIXME
        # TODO use app.auth to build the security scheme
        #      can not auto generate oauth, maybe should use add_documentation({...})


def links():
    pass


def callbacks():
    pass


def security():
    if "flask_oauthlib.provider" in sys.modules.keys():
        return [{"oAuth2": []}]
    elif isinstance(app.auth, TokenAuth):
        return [{"BearerAuth": []}]
    elif isinstance(app.auth, BasicAuth):
        return [{"BasicAuth": []}]


def tags():
    tags = []
    names = []
    for (resource_name, rd) in app.config["DOMAIN"].items():
        if resource_name.endswith("_versions") or rd.get("disable_documentation"):
            continue

        name = rd["item_title"]
        if name in names:
            continue

        tagInfo = {"name": name}
        if "description" in rd:
            tagInfo["description"] = rd["description"]

        names.append(name)
        tags.append(tagInfo)
    return tags


def external_docs():
    pass
