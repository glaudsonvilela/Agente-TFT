"""Map every sealed catalog entry without equating inventory with readiness.

This report is an audit artifact, never a source of executable game rules.
Core contracts stay separate from patch-dependent entities and coefficients.
"""

from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
import hashlib
import json
from pathlib import Path

from ingestion.field_names import resolve_fields
from ingestion.knowledge_release import canonical, read_release
from ingestion.simulation_bindings import load_bindings
from training.compile_effects import compile_catalog
from .attribute_worklist import finite_number, variables_audit
from .coverage import REQUIRED_STATS


def indexed(rows):
    result = {}
    for row in rows:
        key = row["api_name"]
        if key in result:
            raise ValueError(f"Duplicate catalog identity: {key}")
        result[key] = row
    return result


def numeric_fields(description, values):
    names = resolve_fields(description, values)
    return [
        dict(
            key=key,
            name=names.get(key),
            value=value,
            name_status="matched" if key in names else "unresolved",
            semantics_verified=False,
        )
        for key, value in sorted(values.items())
    ]


def build_map(manifest, catalogs, bindings, requirements):
    content = compile_catalog(manifest, catalogs, bindings)
    units = indexed(catalogs["units"]["champions"])
    traits = indexed(catalogs["traits"]["traits"])
    items = indexed(catalogs["items"]["items"])
    if (
        requirements["set_key"] != bindings["set_key"]
        or requirements["patch"] != bindings["patch"]
    ):
        raise ValueError("Requirements belong to a different seasonal pack")
    if set(requirements["traits"]) != set(traits):
        raise ValueError("Every trait needs a reviewed semantic dependency entry")
    trait_ids = {row["name"]: key for key, row in traits.items()}
    entries = []
    for key, row in units.items():
        spec = content["champions"][key]
        rule = bindings["champions"][key]
        ability = row.get("ability") or {}
        variables, invalid = variables_audit(ability)
        entry = dict(
            kind="champion",
            id=key,
            name=row["name"],
            cost=row["cost"],
            identity=rule.get("identity", key),
            ability_name=ability.get("name"),
            catalog_stats=deepcopy(row.get("stats") or {}),
            missing_stats=[
                field
                for field in REQUIRED_STATS
                if not finite_number((row.get("stats") or {}).get(field))
            ],
            ability_fields=numeric_fields(ability.get("description", ""), variables),
            invalid_variable_rows=invalid,
            numeric_formula_source="seasonal_binding" if "spell" in rule else "unbound",
            role=rule.get("role"),
            supported_stars=rule.get("supported_stars", []),
            trait_dependencies=[trait_ids[name] for name in row["traits"]],
            status=spec["ability_status"],
            combat_candidate=not spec.get("unsupported", False),
            blockers=spec.get("ability_blockers", [])
            + (
                [spec["reason"]]
                if spec.get("unsupported") and spec.get("ability_program")
                else []
            ),
            calibration_notes=rule.get("notes", []),
            source_component="units",
            replay_validated=False,
        )
        # A runnable ability can still be rejected by any active unbound trait.
        entry["conditional_trait_blockers"] = [
            tid
            for tid in entry["trait_dependencies"]
            if content["traits"][tid]["status"] != "candidate_not_replay_validated"
        ]
        entries.append(entry)
    for key, row in traits.items():
        spec = content["traits"][key]
        tiers = []
        for raw, compiled in zip(row["effects"], spec["tiers"], strict=True):
            valid_bounds = (
                type(raw["min_units"]) is int and type(raw["max_units"]) is int
            )
            tiers.append(
                dict(
                    minimum=raw["min_units"],
                    maximum=raw["max_units"],
                    bounds_valid=valid_bounds,
                    status=(
                        "blocked"
                        if compiled.get("unsupported") or not valid_bounds
                        else "candidate"
                    ),
                    fields=numeric_fields(row.get("desc", ""), raw["variables"]),
                    numeric_overrides=compiled.get("numeric_overrides", []),
                    replay_validated=False,
                )
            )
        entries.append(
            dict(
                kind="trait",
                id=key,
                name=row["name"],
                status=spec["status"],
                tiers=tiers,
                dependencies=requirements["traits"][key],
                source_component="traits",
                replay_validated=False,
            )
        )
    for key, row in items.items():
        spec = content["items"][key]
        entries.append(
            dict(
                kind="item_catalog",
                id=key,
                name=row["name"],
                status="candidate" if spec.get("combat_handler") else "unbound",
                fields=numeric_fields(row.get("desc", ""), row.get("effects") or {}),
                composition=row.get("composition", []),
                unique=row.get("unique"),
                incompatible_traits=row.get("incompatible_traits", []),
                numeric_overrides=spec.get("numeric_overrides", []),
                set_membership_verified=False,
                blockers=(
                    []
                    if spec.get("combat_handler")
                    else [spec.get("reason", "effect binding missing")]
                ),
                source_component="items",
                replay_validated=False,
            )
        )
    for form in bindings.get("ability_scope", {}).get(
        "alternate_forms_outside_catalog", []
    ):
        entries.append(
            dict(
                kind="alternate_form",
                id=form["identity"] + ":" + form["form"],
                name=form["identity"],
                status="blocked",
                blockers=[form["reason"]],
                source_component="ability_scope",
                replay_validated=False,
            )
        )
    counts = dict(Counter(row["kind"] for row in entries))
    return dict(
        schema_version=1,
        kind="simulation_rule_map",
        patch=bindings["patch"],
        set_key=bindings["set_key"],
        release_sha256=manifest["release_sha256"],
        bindings_sha256=content["bindings_sha256"],
        requirements_sha256=hashlib.sha256(canonical(requirements)).hexdigest(),
        catalog_sources=dict(
            url=manifest["source_url"],
            source_sha256=manifest["source_sha256"],
            components=manifest["components"],
        ),
        sources=bindings["sources"],
        counts=counts,
        entries=entries,
        catalog_inventory_complete=(
            counts.get("champion") == len(units)
            and counts.get("trait") == len(traits)
            and counts.get("item_catalog") == len(items)
        ),
        global_item_catalog_is_current_set_pool=False,
        systems=deepcopy(requirements["systems"]),
        completeness_limits=deepcopy(requirements["completeness_limits"]),
        coverage=content["coverage"],
        all_game_variables_mapped=False,
        all_rules_implemented=False,
        current_patch_training_ready=False,
        runtime_promoted=False,
    )


def write_summary(report, destination):
    def clean(value):
        return str(value).replace("|", "/").replace("\n", " ")

    lines = [
        "# Mapa do simulador TFT",
        "",
        "Inventário integral do catálogo disponível. Regras pendentes continuam explícitas.",
        "",
        "**Não comprova cobertura integral do jogo, treino de partidas completas ou prontidão do coach.**",
        "",
        f"Patch do pacote: {report['patch']}. Catálogo de itens global; pertencimento ao set ainda não confirmado.",
        "",
        "## Sistemas e contratos",
        "",
        "| Sistema | Camada | Estado | O que falta |",
        "|---|---|---|---|",
    ]
    for system in report["systems"]:
        lines.append(
            "| "
            + " | ".join(
                clean(system[k]) if k != "missing" else clean("; ".join(system[k]))
                for k in ("name", "layer", "status", "missing")
            )
            + " |"
        )
    lines += [
        "",
        "## Habilidades e formas",
        "",
        "| ID | Nome | Estado | Combate candidato | Pendências |",
        "|---|---|---|---|---|",
    ]
    for row in report["entries"]:
        if row["kind"] not in ("champion", "alternate_form"):
            continue
        pending = row["blockers"] + row.get("conditional_trait_blockers", [])
        if row.get("missing_stats"):
            pending.append("Atributos ausentes: " + ", ".join(row["missing_stats"]))
        pending += row.get("calibration_notes", [])
        lines.append(
            f"| {clean(row['id'])} | {clean(row['name'])} | {row['status']} | "
            f"{'sim, condicionado às sinergias' if row.get('combat_candidate') else 'não'} | {clean('; '.join(pending))} |"
        )
    lines += [
        "",
        "## Características",
        "",
        "| ID | Nome | Patamares candidatos | Dependências |",
        "|---|---|---|---|",
    ]
    for row in report["entries"]:
        if row["kind"] == "trait":
            tiers = (
                ", ".join(
                    str(t["minimum"])
                    for t in row["tiers"]
                    if t["status"] == "candidate"
                )
                or "nenhum"
            )
            lines.append(
                f"| {row['id']} | {clean(row['name'])} | {tiers} | {clean('; '.join(row['dependencies']))} |"
            )
    lines += [
        "",
        "## Itens e outros registros do catálogo global",
        "",
        f"O JSON contém os {report['counts']['item_catalog']} registros individualmente, com campos numéricos, receitas, estado e procedência.",
        "Aprimoramentos, consumíveis e registros de sets antigos podem aparecer nesse catálogo. IDs não comprovam disponibilidade no patch.",
        "",
        "## Limites de completude",
        "",
    ]
    lines += ["- " + text for text in report["completeness_limits"]]
    if "supplemental_inventory" in report:
        supplement = report["supplemental_inventory"]
        lines += [
            "",
            "## Inventário suplementar online",
            "",
            "Fontes suplementares ainda sem identidade de patch confirmada. Descrições não são handlers.",
            "",
            "| Aprimoramento | Desativado na fonte | Descrição anterior disponível |",
            "|---|---|---|",
        ]
        for row in supplement["augment_index"]:
            lines.append(
                f"| [{clean(row['name'])}]({row['url']}) | "
                f"{'sim' if row['source_reports_disabled'] else 'não informado'} | "
                f"{'sim, conferir identidade' if row['description_mapped'] else 'não'} |"
            )
        lines += [
            "",
            "| Fogo-fátuo | Preço observado | Dependências sugeridas pelo texto |",
            "|---|---|---|",
        ]
        for row in supplement["wisps"]:
            price = str(row["price_gold"]) if row["price_observed"] else "não informado"
            hints = sorted(
                set(row["normal_dependency_hints"] + row["blossom_dependency_hints"])
            )
            lines.append(
                f"| {clean(row['name'])} | {price} | {clean(', '.join(hints))} |"
            )
        lines += [
            "",
            "Os 25 preços ausentes permanecem desconhecidos, sem preenchimento com zero.",
            "Disponibilidade por estágio, fórmulas, probabilidades e interações ainda exigem confirmação.",
            "As variantes de aprimoramentos com nomes iguais precisam de ID e regras de elegibilidade.",
        ]
    destination.write_text("\n".join(lines) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, default=Path("."))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--summary", type=Path)
    parser.add_argument("--supplemental", type=Path)
    args = parser.parse_args()
    selection = json.loads(
        (args.project / "configs/catalog/active-knowledge-release-v1.json").read_text()
    )
    manifest, catalogs = read_release(args.project / selection["reference"])
    pack = (
        args.project
        / "configs/simulation/seasons"
        / selection["set_key"]
        / selection["tft_patch"]
    )
    requirements = json.loads((pack / "mapping-requirements.json").read_text())
    report = build_map(
        manifest, catalogs, load_bindings(pack / "manifest.json"), requirements
    )
    if args.supplemental:
        raw = args.supplemental.read_bytes()
        supplemental = json.loads(raw)
        if supplemental.get("intended_patch") != report["patch"]:
            raise ValueError("Supplemental inventory targets another patch")
        report["supplemental_inventory"] = {
            "sha256": hashlib.sha256(raw).hexdigest(),
            **{
                key: supplemental[key]
                for key in ("sources", "counts", "augment_index", "wisps", "conflicts")
            },
        }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(canonical(report))
    if args.summary:
        args.summary.parent.mkdir(parents=True, exist_ok=True)
        write_summary(report, args.summary)
    print(
        json.dumps(
            dict(
                counts=report["counts"],
                catalog_inventory_complete=report["catalog_inventory_complete"],
                all_game_variables_mapped=False,
            )
        )
    )


if __name__ == "__main__":
    main()
