"""Per-turn, nonblocking strategic missions using native ownership selectors."""
import copy


def ensure_aa_schema(raw):
    from .native_graph import NativeGraphEditor
    editor=NativeGraphEditor(raw)
    for name,fields in [('TGDDescriptorLaunchFortifyAntiAir',['Group','Blocking','ExecuteOnlyOnIAActivated','FreeOrder','OrderCancelable']),
                        ('TGDDescriptorSetVariableIntegerFromUnitGroup',['Group','Variable']),
                        ('TGDDescriptorStrategicMoveAndAttack',['OrderCancelable']),('TGDDescriptorStrategicDefend',['OrderCancelable']),
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
    def one(plan):
        defensive=plan['type'] in {'defend','hold','reserve','support','air_support'}
        cls='TGDDescriptorStrategicDefend' if defensive else 'TGDDescriptorStrategicMoveAndAttack'
        continuous=compiled['adapter'].get('ai_mission_version')==5
        route=plan.get('route',[plan['target']])
        def mission(target):
            remaining=route[route.index(target):] if continuous and not defensive else [target]
            return add(cls,[prop(cls,'Blocking',boolean(False)),prop(cls,'Group',ref(group,'TGDVariableUnitGroup')),
                prop(cls,'ExecuteOnlyOnIAActivated',boolean(False)),prop(cls,'OrderCancelable',boolean(True)),
                prop(cls,'AttackEnemyInRadius',integer(compiled['campaign']['ai_policy']['attack_radius'])),
                prop(cls,'UseOnlyUnitInMissionToAttack',boolean(not compiled['campaign']['ai_policy']['cooperate'])),
                prop(cls,'WaypointReachedRadius',integer(707)),
                prop(cls,'Position' if defensive else 'Positions',ref(tags[target],'TGDTagPosition') if defensive
                     else listref([ref(tags[point],'TGDTagPosition') for point in remaining]))])
        selected=mission(plan['target']);kind=cls
        if not defensive:
            for target in reversed(plan.get('route',[plan['target']])[:-1]):
                move=mission(target)
                selected=add('TGDDescriptorIfThenElse',[
                    prop('TGDDescriptorIfThenElse','Condition',ref(owner(target,side),'TGDConditionPositionInInfluenceMap')),
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
        action,kind=one(plan)
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
        prop('TGDDescriptorSimultaneous','SubActions',listref(branches)),
        prop('TGDDescriptorSimultaneous','NbExecutions',uint(1))])
    return protect(root,'TGDDescriptorSimultaneous')
