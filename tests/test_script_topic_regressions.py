from core.script_quality_gate import evaluate_script_quality


def _script_line(role, text):
    return {"role": role, "text": text}


def test_topic_regression_detached_script_fails():
    topic = "rain asmr falling leaves challenge"
    script_list = [
        _script_line("grandma", "At the end of the old alley, the barber shop waited in silence."),
        _script_line("grandpa", "The cracked mirror inside the barber shop reflected a tired face."),
        _script_line("woman", "Dust hung over the old alley and the barber chair never moved."),
        _script_line("grandma", "At the end of the old alley, the barber shop waited in silence."),
        _script_line("grandpa", "The cracked mirror inside the barber shop reflected a tired face."),
        _script_line("woman", "Dust hung over the old alley and the barber chair never moved."),
        _script_line("grandma", "At the end of the old alley, the barber shop waited in silence."),
        _script_line("grandpa", "The cracked mirror inside the barber shop reflected a tired face."),
        _script_line("woman", "Dust hung over the old alley and the barber chair never moved."),
        _script_line("grandma", "At the end of the old alley, the barber shop waited in silence."),
        _script_line("grandpa", "The cracked mirror inside the barber shop reflected a tired face."),
        _script_line("woman", "Dust hung over the old alley and the barber chair never moved."),
        _script_line("grandma", "At the end of the old alley, the barber shop waited in silence."),
        _script_line("grandpa", "The cracked mirror inside the barber shop reflected a tired face."),
        _script_line("woman", "Dust hung over the old alley and the barber chair never moved."),
        _script_line("grandma", "At the end of the old alley, the barber shop waited in silence."),
        _script_line("grandpa", "The cracked mirror inside the barber shop reflected a tired face."),
        _script_line("woman", "Dust hung over the old alley and the barber chair never moved."),
        _script_line("grandma", "At the end of the old alley, the barber shop waited in silence."),
        _script_line("grandpa", "The cracked mirror inside the barber shop reflected a tired face."),
    ]

    report = evaluate_script_quality(topic, script_list, category="senior", mode="makjang")
    codes = {issue.code for issue in report.issues}

    assert report.passed is False
    assert "topic_detached" in codes
    assert "duplicate_spike" in codes


def test_topic_regression_weak_alignment_warns_but_passes():
    topic = "snowstorm lighthouse harbor suitcase trumpet moonlight lunchbox lantern"
    script_list = [
        _script_line("grandma", "The lunchbox was still warm when she reached the gate."),
        _script_line("grandpa", "He smiled and asked why she wrapped the lunchbox in two towels."),
        _script_line("woman", "She said the lunchbox mattered more than the train schedule."),
        _script_line("grandma", "Inside the lunchbox, rice and eggs were packed with care."),
        _script_line("grandpa", "He joked that the lunchbox could calm any argument."),
        _script_line("woman", "She answered that the lunchbox was the only apology she could carry."),
        _script_line("grandma", "The lunchbox scent followed them down the platform."),
        _script_line("grandpa", "He held the lunchbox with both hands and finally looked relieved."),
        _script_line("woman", "Nobody opened the note yet, but the lunchbox already softened them."),
        _script_line("grandma", "She told him to eat before the soup in the lunchbox turned cold."),
        _script_line("grandpa", "He said he would read the note after he finished the lunchbox."),
        _script_line("woman", "The lights flickered while the lunchbox steam faded into the air."),
    ]

    report = evaluate_script_quality(topic, script_list, category="senior", mode="touching")
    codes = {issue.code for issue in report.issues}

    assert report.passed is True
    assert "topic_alignment" in codes
    assert "topic_detached" not in codes


def test_topic_regression_aligned_script_passes_cleanly():
    topic = "storm bus stop final promise"
    script_list = [
        _script_line("grandma", "Rain hammered the bus stop roof as she clutched the final promise in her pocket."),
        _script_line("grandpa", "He arrived drenched and laughed that even a storm could not cancel this promise."),
        _script_line("woman", "The empty bus stop made their voices sound louder than the storm."),
        _script_line("grandma", "She said the final promise was simple: never disappear without a word again."),
        _script_line("grandpa", "He nodded and pointed at the storm flooding the road beside the bus stop."),
        _script_line("woman", "No buses came, but the bus stop became a shelter for the promise they avoided for years."),
        _script_line("grandma", "She unfolded the paper and read the promise while thunder rolled behind the station sign."),
        _script_line("grandpa", "He answered that the storm used to scare him, but breaking the promise scared him more."),
        _script_line("woman", "A child under the bus stop bench watched them and smiled at the word promise."),
        _script_line("grandma", "She asked whether he would still keep the promise after the storm passed."),
        _script_line("grandpa", "He said the bus stop would remind him every time rain started."),
        _script_line("woman", "The storm eased, but neither of them moved away from the bus stop."),
        _script_line("grandma", "She tucked the promise back into her coat and offered him the dry side of the bench."),
        _script_line("grandpa", "He thanked her and repeated the promise without looking away."),
        _script_line("woman", "When the final bus finally arrived, the storm had already lost its voice."),
        _script_line("grandma", "She told him they did not need the bus yet because the promise came first."),
        _script_line("grandpa", "He agreed that the storm was only weather, but the promise was their decision."),
        _script_line("woman", "The bus stop light reflected in the puddles like a quiet curtain call."),
        _script_line("grandma", "She smiled for the first time that night and called the promise complete."),
        _script_line("grandpa", "Together they stepped out of the bus stop just as the storm finally broke apart."),
    ]

    report = evaluate_script_quality(topic, script_list, category="senior", mode="touching")
    codes = {issue.code for issue in report.issues}

    assert report.passed is True
    assert "topic_alignment" not in codes
    assert "topic_detached" not in codes
