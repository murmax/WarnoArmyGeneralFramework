"""Per-turn, nonblocking strategic missions using native ownership selectors."""
import copy
from .ai_control import mission_cooperates


def battle_profile(policy,side,turn,defensive=False):
    """Native EStrategicBattleDescriptor: Default=0, Agressif=4."""
    return 4 if not defensive and turn<=policy.get('aggressive_until',{}).get(side,0) else 0


def ensure_aa_schema(raw):
    from .native_graph import NativeGraphEditor
    editor=NativeGraphEditor(raw)
    for name,fields in [('TGDDescriptorLaunchFortifyAntiAir',['Group','Blocking','ExecuteOnlyOnIAActivated','FreeOrder','OrderCancelable']),
                        ('TGDDescriptorSetVariableIntegerFromUnitGroup',['Group','Variable']),
                        ('TGDDescriptorStrategicMoveAndAttack',['OrderCancelable','StartBattleDescriptorType']),('TGDDescriptorStrategicDefend',['OrderCancelable','StartBattleDescriptorType']),
                        ('TGDDescriptorAddDetectedUnitsToUnitGroup',['Detector','Group']),
                        ('TGDConditionDetectUnitDansDetecteur',['Detecteur','Contrainte']),
                        ('TGDContrainteOnUnitAllContrainte',['ContrainteList']),
                        ('TGDContrainteOnUnitTag',['Tag']),('TGDContrainteOnUnitTeam',['Camp'])]:
        if name not in editor.graph['classes']:editor.graph['classes'].append(name)
        for key in fields:
            if not any(p['class']==name and p['name']==key for p in editor.graph['properties']):
                editor.graph['properties'].append({'class':name,'class_id':editor.graph['classes'].index(name),'name':key})
    return editor.save()


def scheduled_missions(group,order,side,members,compiled,*,add,prop,ref,boolean,
                       integer,uint,listref,turn_condition,wait_then,owner,tags,protect):
    phases=compiled['campaign']['ai_policy'].get('phase_orders',{})
    changes=next((phases[x] for x in members if x in phases),[])
    aa=any(row['id'] in members and row.get('oob',{}).get('strategic',{}).get('support',{}).get('kind')=='air_defence'
           for row in compiled['battalions'])
    # One-shot ownership latches are private to this operational group. They
    # preserve already secured route stages when rear-area influence changes.
    progress={}
    watchers=[]
    retain=compiled['campaign']['ai_policy'].get('retain_route_progress',False)
    for plan in [order,*changes] if retain else []:
        if plan['type'] in {'defend','hold','reserve','support','air_support'}:continue
        for target in plan.get('route',[plan['target']])[:-1]:
            if target in progress:continue
            variable=add('TGDVariableInteger',[prop('TGDVariableInteger','Value',integer(0))])
            progress[target]=variable
            latch=add('TGDDescriptorModifieVariableInteger',[
                prop('TGDDescriptorModifieVariableInteger','Variable1',ref(variable,'TGDVariableInteger')),
                prop('TGDDescriptorModifieVariableInteger','Value',integer(1)),
                prop('TGDDescriptorModifieVariableInteger','ModificationType',integer(0))])
            watchers.append(ref(wait_then(latch,'TGDDescriptorModifieVariableInteger',owner(target,side)),
                                'TGDDescriptorSequential'))
    def one(plan,turn):
        defensive=plan['type'] in {'defend','hold','reserve','support','air_support'}
        cls='TGDDescriptorStrategicDefend' if defensive else 'TGDDescriptorStrategicMoveAndAttack'
        continuous=compiled['adapter'].get('ai_mission_version',0)>=5
        route=plan.get('route',[plan['target']])
        def mission(target):
            from .ai_distances import mission_radii
            attack_radius,waypoint_radius=mission_radii(compiled,defensive=defensive,
                target=target,final_target=plan['target'],support=plan['type'] in {'support','reserve','air_support'})
            remaining=route[route.index(target):] if continuous and not defensive else [target]
            properties=[prop(cls,'Blocking',boolean(False)),prop(cls,'Group',ref(group,'TGDVariableUnitGroup')),
                prop(cls,'ExecuteOnlyOnIAActivated',boolean(False)),prop(cls,'OrderCancelable',boolean(True)),
                prop(cls,'AttackEnemyInRadius',integer(attack_radius)),
                prop(cls,'UseOnlyUnitInMissionToAttack',boolean(not mission_cooperates(compiled, side))),
                prop(cls,'WaypointReachedRadius',integer(waypoint_radius)),
                prop(cls,'Position' if defensive else 'Positions',ref(tags[target],'TGDTagPosition') if defensive
                     else listref([ref(tags[point],'TGDTagPosition') for point in remaining]))]
            if compiled['adapter'].get('ai_mission_version',0)>=6:
                # Native enum: Default=0, Agressif=4. Scope is this mission,
                # never global constants or the human-controlled army.
                properties.append(prop(cls,'StartBattleDescriptorType',integer(
                    battle_profile(compiled['campaign']['ai_policy'],side,turn,defensive))))
            return add(cls,properties)
        selected=mission(plan['target']);kind=cls
        if not defensive:
            for target in reversed(plan.get('route',[plan['target']])[:-1]):
                move=mission(target)
                condition=owner(target,side);condition_class='TGDConditionPositionInInfluenceMap'
                if retain:
                    compare=add('TGDOperatorIntegerCompare',[prop('TGDOperatorIntegerCompare','Value',integer(1))])
                    completed=add('TGDConditionVariable',[
                        prop('TGDConditionVariable','Variable',ref(progress[target],'TGDVariableInteger')),
                        prop('TGDConditionVariable','Operator',ref(compare,'TGDOperatorIntegerCompare'))])
                    condition=add('TGDConditionOr',[prop('TGDConditionOr','SousConditions',listref([
                        ref(condition,'TGDConditionPositionInInfluenceMap'),ref(completed,'TGDConditionVariable')]))])
                    condition_class='TGDConditionOr'
                selected=add('TGDDescriptorIfThenElse',[
                    prop('TGDDescriptorIfThenElse','Condition',ref(condition,condition_class)),
                    prop('TGDDescriptorIfThenElse','EffetIfTrue',ref(selected,kind)),
                    prop('TGDDescriptorIfThenElse','EffetIfFalse',ref(move,cls))])
                kind='TGDDescriptorIfThenElse'
        if aa and defensive:
            deploy=add('TGDDescriptorLaunchFortifyAntiAir',[
                prop('TGDDescriptorLaunchFortifyAntiAir','Group',ref(group,'TGDVariableUnitGroup')),
                prop('TGDDescriptorLaunchFortifyAntiAir','Blocking',boolean(False)),
                prop('TGDDescriptorLaunchFortifyAntiAir','ExecuteOnlyOnIAActivated',boolean(False)),
                prop('TGDDescriptorLaunchFortifyAntiAir','OrderCancelable',boolean(True)),
                prop('TGDDescriptorLaunchFortifyAntiAir','FreeOrder',boolean(False))])
            selected=add('TGDDescriptorSequential',[
                prop('TGDDescriptorSequential','SubActions',listref([ref(selected,kind),ref(deploy,'TGDDescriptorLaunchFortifyAntiAir')])),
                prop('TGDDescriptorSequential','NbExecutions',uint(1))]);kind='TGDDescriptorSequential'
        return selected,kind
    branches=[]
    for turn in range(order.get('start_turn',1),compiled['campaign']['turns']+1):
        plan=order
        for phase in changes:
            if phase['from_turn']<=turn:plan=phase
        action,kind=one(plan,turn)
        recapture = compiled['campaign']['ai_policy'].get('recapture_if_lost', {}).get(side)
        if recapture:
            recovery, recovery_kind = one({'type': 'counterattack', 'target': recapture,
                                           'route': [recapture]}, turn)
            action = add('TGDDescriptorIfThenElse', [
                prop('TGDDescriptorIfThenElse', 'Condition',
                     ref(owner(recapture, side), 'TGDConditionPositionInInfluenceMap')),
                prop('TGDDescriptorIfThenElse', 'EffetIfTrue', ref(action, kind)),
                prop('TGDDescriptorIfThenElse', 'EffetIfFalse', ref(recovery, recovery_kind))])
            kind = 'TGDDescriptorIfThenElse'
        count=add('TGDVariableInteger',[prop('TGDVariableInteger','Value',integer(0))])
        read=add('TGDDescriptorSetVariableIntegerFromUnitGroup',[
            prop('TGDDescriptorSetVariableIntegerFromUnitGroup','Group',ref(group,'TGDVariableUnitGroup')),
            prop('TGDDescriptorSetVariableIntegerFromUnitGroup','Variable',ref(count,'TGDVariableInteger'))])
        compare=add('TGDOperatorIntegerCompare',[prop('TGDOperatorIntegerCompare','OperatorType',integer(4)),
            prop('TGDOperatorIntegerCompare','Value',integer(0))])
        alive=add('TGDConditionVariable',[prop('TGDConditionVariable','Variable',ref(count,'TGDVariableInteger')),
            prop('TGDConditionVariable','Operator',ref(compare,'TGDOperatorIntegerCompare'))])
        idle=add('TGDDescriptorWaitDuration',[prop('TGDDescriptorWaitDuration','Duree',{'type_id':5,'type':'float32','reference_prefix':False,'value':0.0})])
        guarded=add('TGDDescriptorIfThenElse',[
            prop('TGDDescriptorIfThenElse','Condition',ref(alive,'TGDConditionVariable')),
            prop('TGDDescriptorIfThenElse','EffetIfTrue',ref(action,kind)),
            prop('TGDDescriptorIfThenElse','EffetIfFalse',ref(idle,'TGDDescriptorWaitDuration'))])
        action=add('TGDDescriptorSequential',[prop('TGDDescriptorSequential','SubActions',listref([
            ref(read,'TGDDescriptorSetVariableIntegerFromUnitGroup'),ref(guarded,'TGDDescriptorIfThenElse')])),
            prop('TGDDescriptorSequential','NbExecutions',uint(1))]);kind='TGDDescriptorSequential'
        branches.append(ref(wait_then(action,kind,turn_condition(turn,side)),'TGDDescriptorSequential'))
    root=add('TGDDescriptorSimultaneous',[
        prop('TGDDescriptorSimultaneous','SubActions',listref([*watchers,*branches])),
        prop('TGDDescriptorSimultaneous','NbExecutions',uint(1))])
    return protect(root,'TGDDescriptorSimultaneous')


def validate_refresh_profiles(graph,compiled):
    """Prove per-side/turn profile scope and monotonic route-stage latches."""
    from .bruderkrieg import _property,_reachable_objects
    objects=graph['objects'];checked=set();counts={'aggressive':0,'default':0}
    active=_reachable_objects(graph,compiled['adapter']['script']['root'])
    mission_classes={'TGDDescriptorStrategicMoveAndAttack','TGDDescriptorStrategicDefend'}
    for sequence in objects:
        if sequence['id'] not in active:continue
        if sequence['class']!='TGDDescriptorSequential':continue
        items=_property(sequence,'SubActions')['items']
        if len(items)!=2 or objects[items[0]['object_id']]['class']!='TGDDescriptorWaitCondition':continue
        condition=objects[_property(objects[items[0]['object_id']],'Condition')['object_id']]
        if condition['class']!='TGDConditionAnd':continue
        parts=_property(condition,'SousConditions')['items']
        if len(parts)!=2:continue
        number,owner=[objects[x['object_id']] for x in parts]
        if (number['class']!='TGDConditionVariable' or owner['class']!='TGDConditionStrategicIsPlayerTurn'
                or _property(number,'Variable')['object_id']!=381):continue
        reach=_reachable_objects(graph,items[1]['object_id'])
        if any(objects[i]['class']=='TGDDescriptorWaitCondition' for i in reach):continue
        turn=_property(objects[_property(number,'Operator')['object_id']],'Value')['value']
        side='nato' if _property(owner,'Camp')['object_id']==284 else 'pact'
        for i in reach:
            mission=objects[i]
            if mission['class'] not in mission_classes:continue
            expected=4 if (mission['class']=='TGDDescriptorStrategicMoveAndAttack' and
                turn<=compiled['campaign']['ai_policy'].get('aggressive_until',{}).get(side,0)) else 0
            if _property(mission,'StartBattleDescriptorType')['value']!=expected:
                raise ValueError('AI battle profile crosses its coalition/turn/mission boundary')
            if i not in checked:counts['aggressive' if expected==4 else 'default']+=1
            checked.add(i)
    missions={o['id'] for o in objects if o['id'] in active and o['class'] in mission_classes}
    if checked!=missions:raise ValueError('AI battle profile lacks dated mission coverage')
    latches=set()
    if compiled['campaign']['ai_policy'].get('retain_route_progress'):
        for node in objects:
            if node['id'] not in active:continue
            if node['class']!='TGDConditionOr':continue
            children=[objects[x['object_id']] for x in _property(node,'SousConditions')['items']]
            if len(children)!=2 or [x['class'] for x in children]!=[
                    'TGDConditionPositionInInfluenceMap','TGDConditionVariable']:continue
            variable=_property(children[1],'Variable')['object_id']
            compare=objects[_property(children[1],'Operator')['object_id']]
            if next((p['value'].get('value') for p in compare['properties'] if p['property_name']=='Value'),0)!=1:continue
            writes=[o for o in objects if o['class']=='TGDDescriptorModifieVariableInteger'
                    and _property(o,'Variable1')['object_id']==variable]
            if (len(writes)!=1 or _property(objects[variable],'Value')['value']!=0
                    or _property(writes[0],'Value')['value']!=1
                    or _property(writes[0],'ModificationType')['value']!=0):
                raise ValueError('AI route progress must be a private one-shot monotonic latch')
            writer=writes[0]['id']
            parents=[o for o in objects if o['class']=='TGDDescriptorSequential'
                and len(_property(o,'SubActions')['items'])==2
                and _property(o,'SubActions')['items'][1]['object_id']==writer]
            if len(parents)!=1:raise ValueError('AI route progress lacks one capture observer')
            wait=objects[_property(parents[0],'SubActions')['items'][0]['object_id']]
            observed=objects[_property(wait,'Condition')['object_id']]
            if observed['class']!='TGDConditionPositionInInfluenceMap' or observed['properties']!=children[0]['properties']:
                raise ValueError('AI route progress observes a different waypoint or coalition')
            latches.add(variable)
        if not latches:raise ValueError('AI retained-route latches are missing')
    return {**counts,'remembered_stages':len(latches)}
