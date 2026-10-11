from backend.profiling import profile_dataset


def test_empty_profile():
    profile = profile_dataset([{'name': 'value', 'type': 'REAL'}], [])
    assert profile['quality_score'] == 100
    assert profile['columns'][0]['unique_count'] == 0


def test_outliers_missing_and_nonfinite():
    columns = [{'name': 'value', 'type': 'REAL'}]
    result = profile_dataset(columns, [[1], [2], [3], [4], [100], [None], [float('inf')]])
    value = result['columns'][0]
    assert value['numeric']['outlier_count'] == 1
    assert value['invalid_count'] == 1
    assert value['missing_count'] == 1
    assert value['numeric']['median'] == 3
