//! Controlled facts exercise the real engine; never merged into image observations.
use agente_tft_contracts::{GameState,MatchPhase,Observed,Confidence,ObservationSource,DecisionPacket};
use agente_tft_opportunity_engine::{OpportunityEngine,OpportunityConfig,OpportunityInput,OpportunityReport,OpportunityFacts,BuyOpportunityFact,LevelOpportunityFact,RollOpportunityFact};
use agente_tft_decision_core::DecisionConfig;
use serde_json::{json,Value};
use std::time::Instant;

pub fn evaluate(state:&GameState,facts:OpportunityFacts)->Result<(OpportunityReport,DecisionPacket),String>{
 let e=OpportunityEngine::new(OpportunityConfig::default()).map_err(|e|e.to_string())?;
 let r=e.evaluate(OpportunityInput{state,facts:&facts,meta:None,now_ms:state.observed_at_ms}).map_err(|e|e.to_string())?;
 let d=r.local_decision(DecisionConfig::default());Ok((r,d))
}
fn observed<T>(value:T,at:u64)->Observed<T>{Observed{value,observed_at_ms:at,source:ObservationSource::Simulator,confidence:Confidence::new(0.95).unwrap()}}
pub fn fixture(id:u64,at:u64,case:usize)->Result<Value,String>{
 if case>3{return Err("fixture case must be 0..3".into())}
 let t=Instant::now();let mut s=GameState::empty(at);s.revision=id;s.phase=MatchPhase::Planning;
 s.match_id=Some("E1-CONTROLLED-NOT-A-MATCH".into());s.overall_confidence=Confidence::new(0.95).unwrap();
 s.player.gold=Some(observed(50,at));s.player.level=Some(observed(7,at));s.player.hp=Some(observed(70,at));
 let mut f=OpportunityFacts::default();let c=Confidence::new(0.95).unwrap();
 if case==1{f.buys.push(BuyOpportunityFact{shop_slot:0,unit_id:"FIXTURE_A".into(),gold_cost:3,closes_upgrade:true,contested_copies:None,confidence:c});}
 if case==2{f.levels.push(LevelOpportunityFact{target_level:8,gold_cost:12,expected_board_gain:Some(0.9),slots_gained:1,confidence:c});}
 if case==3{for budget in [10,20,30]{f.rolls.push(RollOpportunityFact{budget_gold:budget,stop_condition:Some("Fim do cenário controlado".into()),target_unit_id:None,probability_at_least_one:Some(0.85),expected_target_copies:Some(1.6),interest_lost:Some(2),contested_copies:None,confidence:c});}}
 let facts=serde_json::to_value(&f).map_err(|e|e.to_string())?;
 let (report,decision)=evaluate(&s,f)?;let elapsed=t.elapsed().as_secs_f64()*1000.;
 Ok(json!({"id":id,"source_ms":at,"origin":"fixture_input","fixture_case":case,"state":s,"facts":facts,"report":report,"decision":decision,
   "spans":[{"stage":"fixture_build_and_real_engine","start_ms":0,"duration_ms":elapsed}],"native_ms":elapsed,
   "hud":null,"shop":null,"controls":null,"board":null,"blockers":[],"canonical_game_state_updated":false,"profile_promoted":false}))
}
#[cfg(test)] mod tests{
 use super::*;
 #[test] fn fixtures_are_provenanced(){for i in 0..4{let r=fixture(1,42,i).unwrap();assert_eq!(r["origin"],"fixture_input");assert!(r["report"]["all"].as_array().unwrap().len()>0);}}
 #[test] fn incomplete_state_does_not_invent_facts(){let (_,d)=evaluate(&GameState::empty(0),OpportunityFacts::default()).unwrap();assert!(matches!(d.action,agente_tft_contracts::Action::Wait));}
 #[test] fn fixture_not_infinite(){assert!(fixture(1,1,4).is_err());}
}
