//will incentivize every user for complianceApp-30 for 4 Cedis
function complianceApp(args) {
    compliance_list = [];

    compliances_to_issue = 1 - args.compliance_app_payments;
    for(let i = 0; i < compliances_to_issue; i++) {
        var obj = {};
        obj.amount = 4;
        obj.incentive_type = 'complianceApp';
        obj.incentive_id = (i+1)*30;
        compliance_list.push(obj);
    }

    return compliance_list;
}

//will incentivize every user for complianceApp-30 for 4 Cedis
function compliancePowerwatch(args) {
    compliance_list = [];

    if(args.powerwatch == true) {

        compliances_to_issue = 1 - args.compliance_powerwatch_payments;
        for(let i = 0; i < compliances_to_issue; i++) {
            var obj = {};
            obj.amount = 5;
            obj.incentive_type = 'compliancePowerwatch';
            obj.incentive_id = (i+1)*30;
            compliance_list.push(obj);
        }
    }

    return compliance_list;
}

module.exports = {
    complianceApp,
    compliancePowerwatch,
};
