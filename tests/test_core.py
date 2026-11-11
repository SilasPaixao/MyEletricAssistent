import json
from pathlib import Path
import pytest
from app.core import load_entries, validate_photo, planned_to_used, MyEAError

def test_load(tmp_path):
    (tmp_path/'a.jpg').write_bytes(b'abc')
    (tmp_path/'data.json').write_text(json.dumps({'demandas':[{'id_referencia':'MYEA-1','fotos':['a.jpg']}]}))
    e = load_entries(tmp_path/'data.json', tmp_path)
    assert e[0].reference == 'MYEA-1'
    validate_photo(e[0])

def test_no_photo():
    from app.core import DemandEntry
    with pytest.raises(MyEAError, match='principal'):
        validate_photo(DemandEntry('MYEA-1', []))

def test_path_escape(tmp_path):
    (tmp_path/'data.json').write_text('[{"id_referencia":"MYEA-1","fotos":["../other.jpg"]}]')
    with pytest.raises(MyEAError, match='fora'):
        load_entries(tmp_path/'data.json', tmp_path)

def test_materials():
    assert planned_to_used({'plannedMaterials':[{'materialId':'abc','quantity':2}]}) == [{'materialId':'abc','quantity':2}]

def test_invalid_material():
    with pytest.raises(MyEAError): planned_to_used({'plannedMaterials':[{'materialId':'abc','quantity':0}]})
