const examState={catalog:[],current:null,totalRemaining:0,questionRemaining:0,timer:null,submitting:false,historyLoaded:false};
const examPatterns={GENERAL:{questions:10,minutes:10,negative:0,hint:'Custom practice: choose your own question count and time.'},IBPS_PO_PRELIMS:{questions:100,minutes:60,negative:.25,hint:'IBPS PO prelims preset: 100 questions, 60 minutes, three separately timed sections, 0.25 negative mark per wrong answer.'},SBI_PO_PRELIMS:{questions:100,minutes:60,negative:.25,hint:'SBI PO prelims preset: 100 questions, 60 minutes, English, Quantitative Aptitude and Reasoning, 0.25 negative mark per wrong answer.'},SSC_CGL_TIER1:{questions:100,minutes:60,negative:.5,hint:'SSC CGL Tier-I preset: 100 questions, 60 minutes, four 25-question sections, 0.50 negative mark per wrong answer.'}};
const examEl=id=>document.getElementById(id);
const examClock=seconds=>`${String(Math.max(0,Math.floor(seconds/60))).padStart(2,'0')}:${String(Math.max(0,seconds%60)).padStart(2,'0')}`;
const examSubmissionKey=()=>globalThis.crypto?.randomUUID?.()||`exam-${Date.now()}-${Math.random().toString(16).slice(2)}`;

async function loadExamCatalog(){
  try{
    examState.catalog=state.catalog.length?state.catalog:await api('/api/catalog');
    const options='<option value="">Select a subject</option>'+examState.catalog.map(item=>`<option value="${escapeHtml(item.subject)}">${escapeHtml(item.subject)} (${item.topics.length} topics)</option>`).join('');
    examEl('examSubject').innerHTML=options;
    examEl('examSubjectChecks').innerHTML=examState.catalog.map((item,index)=>`<label><input type="checkbox" value="${escapeHtml(item.subject)}" ${index<2?'checked':''}><span>${escapeHtml(item.subject)}</span><small>${item.topics.length} topics</small></label>`).join('');
    refreshExamTopics();
  }catch(error){showExamFormError(error.message||'Approved subjects could not be loaded.');}
}

function refreshExamTopics(){
  const subject=examEl('examSubject').value,item=examState.catalog.find(entry=>entry.subject===subject);
  examEl('examTopicSuggestions').innerHTML=(item?.topics||[]).map(topic=>`<option value="${escapeHtml(topic)}"></option>`).join('');
}

function updateExamType(){
  const type=examEl('examType').value,overall=type==='OVERALL',topic=type==='TOPIC';
  examEl('examSingleSubjectField').classList.toggle('hidden',overall);
  examEl('examOverallSubjects').classList.toggle('hidden',!overall);
  examEl('examTopicField').classList.toggle('hidden',!topic);
  examEl('examSubject').required=!overall;
  examEl('examTopic').required=topic;
  if(!topic)examEl('examTopic').value='';
}
function updateExamPattern(){const pattern=examPatterns[examEl('examPattern').value]||examPatterns.GENERAL,general=examEl('examPattern').value==='GENERAL';examEl('examQuestionCount').value=pattern.questions;examEl('examTime').value=pattern.minutes;examEl('examQuestionCount').readOnly=!general;examEl('examTime').readOnly=!general;examEl('examPatternHint').textContent=pattern.hint}

function showExamFormError(message){const box=examEl('examFormError');box.textContent=message;box.classList.remove('hidden');}
function clearExamFormError(){examEl('examFormError').classList.add('hidden');}
function stopExamTimer(){clearInterval(examState.timer);examState.timer=null;}

function renderExamSession(exam){
  stopExamTimer();examState.current=exam;
  if(exam.status==='COMPLETED'){renderExamResults(exam);return;}
  examEl('examSetupPanel').classList.add('hidden');examEl('examResults').classList.add('hidden');examEl('examSession').classList.remove('hidden');
  examEl('examSessionName').textContent=exam.exam_name;
  examEl('examSessionMeta').textContent=`${String(exam.exam_pattern||'GENERAL').replaceAll('_',' ')} · ${exam.exam_type} · ${exam.difficulty} · ${exam.total_questions} questions · ${exam.total_time_minutes} minutes`;
  if(exam.status==='READY'){
    examEl('examSessionStatus').textContent='EXAM READY';examEl('examQuestionNumber').textContent='';examEl('examQuestionSubject').textContent='';
    examEl('examQuestionText').textContent='Your verified question set is ready. The total and per-question timers begin only when you start.';
    examEl('examOptions').innerHTML='';examEl('examProgressBar').style.width='0%';examEl('examTotalTimer').textContent=examClock(exam.total_time_minutes*60);examEl('examQuestionTimer').textContent='—';
    examEl('finishExamButton').classList.add('hidden');examEl('nextExamButton').textContent='Start exam';return;
  }
  examEl('examSessionStatus').textContent='EXAM IN PROGRESS';examEl('finishExamButton').classList.remove('hidden');
  const q=exam.current_question;
  if(!q){examEl('examSessionError').textContent='The next question is unavailable. Finish the exam to preserve your attempt.';examEl('examSessionError').classList.remove('hidden');return;}
  examEl('examSessionError').classList.add('hidden');examEl('examQuestionNumber').textContent=`Question ${q.position} of ${exam.total_questions}`;
  examEl('examQuestionSubject').textContent=[q.subject,q.topic].filter(Boolean).join(' · ');examEl('examQuestionText').textContent=q.question_text;
  examEl('examOptions').innerHTML=q.options.map((option,index)=>`<label><input type="radio" name="examOption" value="${index}"><span><b>${String.fromCharCode(65+index)}</b>${escapeHtml(option)}</span></label>`).join('');
  examEl('examProgressBar').style.width=`${Math.max(0,Math.min(100,((q.position-1)/exam.total_questions)*100))}%`;
  examEl('nextExamButton').textContent=q.position===exam.total_questions?'Submit exam':'Next question';
  examState.totalRemaining=Number(exam.remaining_seconds||0);examState.questionRemaining=Number(q.remaining_seconds||0);paintExamTimers();
  examState.timer=setInterval(async()=>{examState.totalRemaining--;examState.questionRemaining--;paintExamTimers();if(examState.totalRemaining<=0){stopExamTimer();await finishCurrentExam(false);return}if(examState.questionRemaining<=0){stopExamTimer();await submitCurrentAnswer(null,true)}},1000);
}

function paintExamTimers(){examEl('examTotalTimer').textContent=examClock(examState.totalRemaining);examEl('examQuestionTimer').textContent=examClock(examState.questionRemaining);examEl('examQuestionTimer').classList.toggle('warning',examState.questionRemaining<=10);}

async function submitCurrentAnswer(selected=null,timedOut=false){
  if(examState.submitting||!examState.current?.current_question)return;examState.submitting=true;stopExamTimer();
  const button=examEl('nextExamButton');button.disabled=true;
  try{
    if(selected===null&&!timedOut){const checked=document.querySelector('input[name="examOption"]:checked');selected=checked?Number(checked.value):null;}
    const exam=await api(`/api/exams/${examState.current.id}/questions/${examState.current.current_question.id}/answer`,{method:'POST',body:JSON.stringify({selected_index:selected,timed_out:timedOut,submission_key:examSubmissionKey()})});
    renderExamSession(exam);loadExamHistory();
  }catch(error){examEl('examSessionError').textContent=error.message||'The answer could not be saved. Retry before continuing.';examEl('examSessionError').classList.remove('hidden');try{renderExamSession(await api(`/api/exams/${examState.current.id}`));}catch{}}
  finally{examState.submitting=false;button.disabled=false;}
}

async function finishCurrentExam(ask=true){
  if(!examState.current||examState.submitting)return;if(ask&&!confirm('Finish this exam now? Remaining questions will be marked unanswered.'))return;
  examState.submitting=true;stopExamTimer();
  try{renderExamResults(await api(`/api/exams/${examState.current.id}/finish`,{method:'POST',body:'{}'}));loadExamHistory();}
  catch(error){examEl('examSessionError').textContent=error.message||'The exam could not be finished.';examEl('examSessionError').classList.remove('hidden');}
  finally{examState.submitting=false;}
}

function renderExamResults(exam){
  stopExamTimer();examState.current=exam;examEl('examSetupPanel').classList.add('hidden');examEl('examSession').classList.add('hidden');examEl('examResults').classList.remove('hidden');
  examEl('examScoreGrid').innerHTML=[['Marks',`${exam.marks}/${exam.total_questions}`],['Percentage',`${Number(exam.percentage).toFixed(1)}%`],['Correct',exam.correct_count],['Incorrect',exam.incorrect_count],['Negative / wrong',Number(exam.negative_mark_per_wrong||0).toFixed(2)],['Time taken',examClock(exam.time_taken_seconds)]].map(item=>`<div><span>${item[0]}</span><strong>${item[1]}</strong></div>`).join('');
  examEl('examAnalysis').innerHTML=(exam.analysis||[]).map(item=>{const selected=item.selected_index===null||item.selected_index===undefined?'Not answered':item.options[item.selected_index];const pages=item.source_page_start?` · page ${item.source_page_start}${item.source_page_end&&item.source_page_end!==item.source_page_start?`–${item.source_page_end}`:''}`:'';return `<details class="exam-review ${item.is_correct?'correct':item.answer_status==='ANSWERED'?'incorrect':'unanswered'}"><summary><span>Q${item.position}</span><strong>${escapeHtml(item.question_text)}</strong><b>${item.is_correct?'Correct':item.answer_status==='ANSWERED'?'Incorrect':'Unanswered'}</b></summary><div><p><em>Your answer:</em> ${escapeHtml(selected)}</p><p><em>Correct answer:</em> ${escapeHtml(item.options[item.correct_index])}</p><p>${escapeHtml(item.explanation)}</p><small>${escapeHtml(item.source_title)}${pages} · ${escapeHtml(item.evidence_id)}</small></div></details>`}).join('');
  examEl('examResults').scrollIntoView({behavior:'smooth'});
}

async function loadExamHistory(){
  try{const items=await api('/api/exams/history');examState.historyLoaded=true;examEl('examHistory').innerHTML=items.length?items.map(item=>`<button type="button" data-exam-id="${item.id}"><span><strong>${escapeHtml(item.exam_name)}</strong><small>${escapeHtml(item.subjects||'')} · ${escapeHtml(item.difficulty)} · ${item.total_questions} questions</small></span><span class="exam-history-result">${item.status==='COMPLETED'?`${Number(item.percentage).toFixed(1)}%`:escapeHtml(item.status.replace('_',' '))}</span></button>`).join(''):'<div class="empty-mini">No examinations created yet.</div>';}
  catch(error){examEl('examHistory').innerHTML=`<div class="empty-mini">${escapeHtml(error.message||'Exam history is unavailable.')}</div>`;}
}

examEl('examType').addEventListener('change',updateExamType);examEl('examPattern').addEventListener('change',updateExamPattern);examEl('examSubject').addEventListener('change',refreshExamTopics);
examEl('examForm').addEventListener('submit',async event=>{event.preventDefault();clearExamFormError();const type=examEl('examType').value;const subjects=type==='OVERALL'?[...examEl('examSubjectChecks').querySelectorAll('input:checked')].map(input=>input.value):[examEl('examSubject').value].filter(Boolean);const payload={exam_name:examEl('examName').value,exam_pattern:examEl('examPattern').value,exam_type:type,subjects,topic:examEl('examTopic').value,difficulty:examEl('examDifficulty').value,question_count:Number(examEl('examQuestionCount').value),total_time_minutes:Number(examEl('examTime').value)};const button=examEl('generateExamButton');button.disabled=true;button.querySelector('span').textContent='Generating and checking questions…';try{renderExamSession(await api('/api/exams/generate',{method:'POST',body:JSON.stringify(payload)}));loadExamHistory();}catch(error){showExamFormError(error.message||'The examination could not be generated. Your configuration is preserved so you can retry.');}finally{button.disabled=false;button.querySelector('span').textContent='Generate examination';}});
examEl('nextExamButton').addEventListener('click',async()=>{if(examState.current?.status==='READY'){try{renderExamSession(await api(`/api/exams/${examState.current.id}/start`,{method:'POST',body:'{}'}));}catch(error){examEl('examSessionError').textContent=error.message||'The exam could not be started.';examEl('examSessionError').classList.remove('hidden');}return}submitCurrentAnswer();});examEl('finishExamButton').addEventListener('click',()=>finishCurrentExam(true));
examEl('newExamButton').addEventListener('click',()=>{stopExamTimer();examState.current=null;examEl('examResults').classList.add('hidden');examEl('examSession').classList.add('hidden');examEl('examSetupPanel').classList.remove('hidden');examEl('examName').focus();});
examEl('refreshExamHistory').addEventListener('click',loadExamHistory);
examEl('examHistory').addEventListener('click',async event=>{const button=event.target.closest('[data-exam-id]');if(!button)return;try{renderExamSession(await api(`/api/exams/${button.dataset.examId}`));}catch(error){showExamFormError(error.message||'The saved exam could not be opened.');}});
window.addEventListener('exam:view',()=>{if(!examState.catalog.length)loadExamCatalog();loadExamHistory();});
updateExamType();updateExamPattern();
