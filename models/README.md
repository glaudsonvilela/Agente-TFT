# models/

Metadados e manifests de modelos.

Arquivos grandes (`.onnx`, `.pt`, `.pth`) não entram no Git nesta fase. Cada modelo deve ter manifest com:

- name;
- semantic version;
- training dataset/version;
- patch coverage;
- input/output schema;
- metrics;
- hash;
- export settings.
