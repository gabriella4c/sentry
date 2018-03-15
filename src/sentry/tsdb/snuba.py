from __future__ import absolute_import

from dateutil.parser import parse as parse_datetime
import json
import requests
import six

from sentry.tsdb.base import BaseTSDB, TSDBModel
from sentry.utils.dates import to_timestamp

from sentry.models import GroupHash, Environment


class SnubaTSDB(BaseTSDB):
    """
    A time series query interface to Snuba

    Write methods are not supported, as the raw data from which we generate our
    time series is assumed to already exist in snuba.

    Read methods are supported only for models based on group/event data and
    will return empty results for unsupported models.
    """
    SNUBA = 'http://localhost:5000'

    def __init__(self, **options):
        super(SnubaTSDB, self).__init__(**options)

    def model_columns(self, model):
        """
        Translates TSDB models into the required columns for querying snuba.
        Returns a tuple of (groupby_column, aggregateby_column)
        """
        return {
            TSDBModel.project: ('project_id', None),
            TSDBModel.group: ('issue', None),
            TSDBModel.release: ('release', None),
            TSDBModel.users_affected_by_group: ('issue', 'user_id'),
            TSDBModel.users_affected_by_project: ('project_id', 'user_id'),
            TSDBModel.users_affected_by_project: ('project_id', 'user_id'),
            TSDBModel.frequent_environments_by_group: ('issue', 'environment'),
            TSDBModel.frequent_releases_by_group: ('issue', 'release'),
            TSDBModel.frequent_issues_by_project: ('project_id', 'issue'),
        }.get(model, None)

    def normalize_keys(self, items):
        """
        Returns a normalized set of keys based on the various formats accepted
        by TSDB methods. The input is either just a plain list of keys for the
        top level or a `{level1_key: [level2_key, ...]}` dictionary.
        """
        if isinstance(items, list):
            return (items, None)
        elif isinstance(items, dict):
            return (items.keys(), list(set.union(*(set(v) for v in items.values()))))
        else:
            return (None, None)

    def get_data(self, model, keys, start, end, rollup=None, environment_id=None,
                 aggregation='count', group_on_model=True, group_on_time=False):
        model_columns = self.model_columns(model)

        if model_columns is None:
            return None

        model_group, model_aggregate = model_columns

        conditions = []
        keys_map = dict(zip(model_columns, self.normalize_keys(keys)))
        for keycol in keys_map:
            if keycol is not None and keys_map[keycol] is not None:
                conditions.append((keycol, 'IN', keys_map[keycol]))

        groupby = []
        if group_on_model and model_group is not None:
            groupby.append(model_group)
        if group_on_time:
            groupby.append('time')
        if aggregation == 'count' and model_aggregate is not None:
            # Special case, because count has different semantics, we change:
            # `COUNT(model_aggregate)` to `COUNT() GROUP BY model_aggregate`
            groupby.append(model_aggregate)
            model_aggregate = None

        if environment_id is not None:
            conditions.append(('environment', '=', get_environment_name(environment_id)))

        # project_ids will be the set of projects either referenced
        # directly as passed-in keys for project_id, or indrectly (eg the
        # set of projects that are related to the passed-in set of issues)
        project_ids = [get_project_ids(k, ids) for k, ids in six.iteritems(keys_map)]
        project_ids = list(set.intersection(*[set(ids) for ids in project_ids if ids]))

        # If the grouping, aggregation, or any of the conditions reference `issue`
        # we need to fetch the issue definitions (issue -> fingerprint hashes)
        references_issues = 'issue' in groupby + [model_aggregate] + [c[0] for c in conditions]
        # TODO filter issues here to the ones actually referenced (or passed in)
        issues = get_project_issues(project_ids) if references_issues else None

        url = '{0}/query'.format(self.SNUBA)
        request = {k: v for k, v in six.iteritems({
            'from_date': start.isoformat(),
            'to_date': end.isoformat(),
            'conditions': conditions,
            'groupby': groupby,
            'project': project_ids,
            'aggregation': aggregation,
            'aggregateby': model_aggregate,
            'granularity': rollup,
            'issues': issues,
        }) if v is not None}

        response = requests.post(url, data=json.dumps(request))
        # TODO handle error responses
        response = json.loads(response.text)

        # Validate and scrub response
        expected_cols = groupby + ['aggregate']
        assert all(c['name'] in expected_cols for c in response['meta'])
        for d in response['data']:
            if 'time' in d:
                d['time'] = int(to_timestamp(parse_datetime(d['time'])))
            if d['aggregate'] is None:
                d['aggregate'] = 0

        return self.nest_groups(response['data'], groupby)

    def nest_groups(self, data, groups):
        """
        Build a nested mapping from the response rows. Each group column
        gives a new level of nesting and the leaf result is the aggregate
        """
        if not groups:
            return data[0]['aggregate'] if data else None
        else:
            g, rest = groups[0], groups[1:]
            inter = {}
            for d in data:
                inter.setdefault(d[g], []).append(d)
            return {k: self.nest_groups(v, rest) for k, v in six.iteritems(inter)}

    def get_range(self, model, keys, start, end, rollup=None, environment_id=None):
        result = self.get_data(model, keys, start, end, rollup, environment_id,
                               aggregation='count', group_on_time=True)

        # turn {group:{timestamp:count}} mapping into {group:[(timestamp, count), ...]}
        for k in result:
            result[k] = sorted(result[k].items())

        return result

    def get_distinct_counts_series(self, model, keys, start, end=None,
                                   rollup=None, environment_id=None):
        result = self.get_data(model, keys, start, end, rollup, environment_id,
                               aggregation='uniq', group_on_time=True)

        # turn timestamp:count mapping into timestamp-sorted list of tuples
        # convert
        #    {group:{timestamp:count, ...}}
        # into
        #    {group: [(timestamp, count), ...]}
        return {k: sorted(result[k].items()) for k in result}

    def get_distinct_counts_totals(self, model, keys, start, end=None,
                                   rollup=None, environment_id=None):
        return self.get_data(model, keys, start, end, rollup, environment_id,
                             aggregation='uniq')

    def get_distinct_counts_union(self, model, keys, start, end=None,
                                  rollup=None, environment_id=None):
        return self.get_data(model, keys, start, end, rollup, environment_id,
                             aggregation='uniq', group_on_model=False)

    def get_most_frequent(self, model, keys, start, end=None,
                          rollup=None, limit=10, environment_id=None):
        aggregation = 'topK({})'.format(limit)
        result = self.get_data(model, keys, start, end, rollup, environment_id,
                               aggregation=aggregation)

        # convert
        #    {group:[top1, ...]}
        # into
        #    {group: [(top1, score), ...]}
        for k in result:
            item_scores = [(v, float(i + 1)) for i, v in enumerate(reversed(result[k]))]
            result[k] = list(reversed(item_scores))

        return result

    def get_most_frequent_series(self, model, keys, start, end=None,
                                 rollup=None, limit=10, environment_id=None):
        aggregation = 'topK({})'.format(limit)
        result = self.get_data(model, keys, start, end, rollup, environment_id,
                               aggregation=aggregation, group_on_time=True)

        # convert
        #    {group:{timestamp:[top1, ...]}}
        # into
        #    {group: [(timestamp, {top1: score, ...}), ...]}
        for k in result:
            result[k] = sorted([
                (timestamp, {v: float(i + 1) for i, v in enumerate(reversed(topk))})
                for (timestamp, topk) in result[k].items()
            ])

        return result

    def get_frequency_series(self, model, items, start, end=None,
                             rollup=None, environment_id=None, limit=10):
        result = self.get_data(model, items, start, end, rollup, environment_id,
                               aggregation='count', group_on_time=True)
        # convert
        #    {group:{timestamp:{agg:count}}}
        # into
        #    {group: [(timestamp, {agg: count, ...}), ...]}
        return {k: result[k].items() for k in result}

    def get_frequency_totals(self, model, items, start, end=None, rollup=None, environment_id=None):
        return self.get_data(model, items, start, end, rollup, environment_id,
                             aggregation='count')

    def get_optimal_rollup(self, start):
        """
        Always return the smallest rollup as we can bucket on any granularity.
        """
        return self.rollups.keys()[0]


# The following are functions for resolving information from sentry models
# about projects, environments, and issues (groups). Having the TSDB
# implementation have to know about these relationships is not ideal, and
# couples this tsdb implementation to django model code, but is currently
# implemented here for simplicity.

def get_environment_name(environment_id):
    """
    Get an environment name from an id.
    """
    return Environment.objects.get(pk=environment_id).name


def get_project_issues(project_ids):
    """
    Get a list of issues and associated fingerprint hashes for a project.
    """
    project_ids = project_ids if isinstance(project_ids, list) else [project_ids]
    result = {}
    hashes = GroupHash.objects.filter(project__in=project_ids).values_list('group_id', 'hash')
    for gid, hsh in hashes:
        result.setdefault(gid, []).append(hsh)
    return list(result.items())


def get_project_ids(model, model_ids):
    """
    Get the project_ids from a model that has a foreign key to project.
    """
    if model == "project_id":
        return model_ids
    else:
        # TODO return the set of project_id foreign keys for the model
        # objects
        return []
